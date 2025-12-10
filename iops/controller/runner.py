
from iops.utils.logger import HasLogger
from iops.controller.planner import BasePlanner
from iops.controller.executors import BaseExecutor
from iops.utils.generic_config import GenericBenchmarkConfig
from iops.utils.execution_matrix import build_execution_matrix

from typing import Dict, Any
from datetime import datetime
from pathlib import Path
import json

class IOPSRunner(HasLogger):
    def __init__(self, cfg: GenericBenchmarkConfig, args):
        super().__init__()
        self.cfg = cfg
        self.args = args
        self.planner = BasePlanner.build(cfg=self.cfg)
        self.executor = BaseExecutor.build(cfg=self.cfg)

    def run(self):
        self.logger.info("Starting IOPS Runner...")

        test_count = 0

        while True:
            test = self.planner.next_test()
            if test is None:
                break

            test_count += 1
            # run test
            # placeholder for actual test execution logic            
            if self.args.log_level.upper() == 'DEBUG':
                self.logger.debug(test.describe())
            else:
                self.logger.info(test)
            

        self.logger.info("All tests have been planned. Total tests: %d", test_count)
        self.logger.info("IOPS Runner finished.")
            

     
        
            


       
       
        

