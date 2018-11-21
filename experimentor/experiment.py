from typing import Iterable, Dict
from .measurements import Measurement
from .protocol import Protocol
import logging
import os
import time
import datetime
import pymongo


def print_state_to_stdout(state):
    for dev, d in state.items():
        print(f"{dev}:")
        print(' ; '.join([f"{k}={v}" for k,v in d.items()] ))

class Experiment:
    attributes = ['name', 'wd', 'metadata']
    connected = True
    def __init__(self, name, system, working_dir: str, protocol_file: str,
                 measurements: Iterable[Measurement], metadata={},
                 validate_state=False, mongodb=None):
        self.name = name
        self.system = system
        self.system.experiment = self
        self.wd = working_dir
        self.protocol_file = protocol_file
        self.measurements = measurements
        self.validate_state = validate_state
        self.metadata = metadata

        if mongodb is not None:
            client = pymongo.MongoClient()
            self.db = client[mongodb]
        else:
            self.db = None

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    def run(self, startfrom=0, skip_idxs=(), print_datetime=False,  print_state=False, print_state_idx=False, do_startup_checks=True, get_initial_state=True):
        self.setup_logging()
        if do_startup_checks:
            self.startup_checks()

        if get_initial_state:
            state = self.system.get_state()
            self.logger.info("Current State:")
            self.logger.info(str(state))
        else:
            state = {}

        backlog = {}
        for idx, skip, running_state, new_state in Protocol.from_config_file(self.protocol_file):
            if not idx:
                self.system.set_state(running_state)
                
            if print_datetime:
                print('-'*60)
                print(datetime.datetime.utcnow())
            if print_state_idx:
                print(f"At state {idx}")

            state.update(running_state)
            if idx<startfrom or (idx in skip_idxs) or skip:
                backlog.update(running_state)
                print_state_to_stdout(running_state)
                print(f"skipping state {idx}.")
                continue

            if len(backlog):
                self.system.set_state(backlog)
                state.update(backlog)
                backlog = {}
            
            if print_state:
                print_state_to_stdout(new_state)

            self.system.set_state(new_state)
            if self.validate_state:
                state = self.system.get_state()
            self.logger.info("Finished moving to new state. State changes:")
            self.logger.info(str(new_state))
            for measurement in self.measurements:
                measurement.perform(idx, self.system, state)

    def startup_checks(self):
        self.logger.info("Checking that all devices are connected.")
        for dev in self.system.devices:
            if getattr(self.system, dev).connected:
                self.logger.info(f"{dev} is connected.")
            else:
                self.logger.info(f"{dev} is NOT connected. quitting.")
                raise RuntimeError(f"{dev} is NOT connected.")

    def setup_logging(self):
        fname = '_'.join([self.name, time.strftime("%Y%m%d_%H%M%S")])+".log"
        folder = os.path.join(self.wd, self.name)

        try:
            os.mkdir(folder)
        except FileExistsError:
            pass

        path = os.path.join(folder,fname)
        with open(path, 'w') as f:
            f.write(f"{datetime.datetime.utcnow()}:   {self.name} started.\nMetadata:\n\n")
            for k,v in self.metadata.items():
                f.write(f"{k} : {v}\n")
            with open(self.protocol_file, "r") as pf:
                f.write('='*25 + "  Protocol  " + '='*25 +'\n\n')
                for line in pf:
                    f.write(line)
                f.write('\n\n'+'='*60+'\n\n')

        if self.db is not None:
            
            doc = {
                "creation_date": datetime.datetime.utcnow(),
                "document_type": "experiment",
                "data": self.metadata,
                "experiment_name": self.name,
                "experiment_class": self.__class__.__name__,
                "protocol_file_path": self.protocol_file,
            }
            self.db[self.name].insert_one(doc)

        
        fh = logging.FileHandler(path)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        fh.setLevel(logging.INFO)
        self.logger.addHandler(fh)


