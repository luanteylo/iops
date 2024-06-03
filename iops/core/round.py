from iops.core.config import IOPSConfig
from iops.core.tests import Test
from iops.util.generator import Graphs
from iops.util.tags import TestType, Pattern, FileMode, SearchType

import pandas as pd
import subprocess
import random
from typing import List
from pathlib import Path
from rich.console import Console
from abc import ABC, abstractmethod


class Round:
    """
    Represents a round of tests, generating and managing Test instances
    based on the configured test type.
    """
    _id_counter = 0

    def __init__(self, pattern: Pattern, file_mode: FileMode, config: IOPSConfig, test_type: TestType, initial_parameters: dict):
        type(self)._id_counter += 1
        self.round_id = self._id_counter
        
        self.pattern = pattern
        self.file_mode = file_mode
        self.config = config
        self.test_type = test_type        
        self.initial_parameters = initial_parameters

        self.best_bw = None
        self.best_df = None
        self.best_parameter = None
        
        self.round_path = self.config.workdir / self.test_type.name.lower() / f"round_{self.round_id}"
        # create the directory
        self.round_path.mkdir(parents=True, exist_ok=True)

        # create a list of tests to store all the tests
        self.list_test : List[Test] = []
                
        self.df = None
        self.csv_file = self.round_path / f"{self.test_type.name}_{self.round_id}.csv"
        self.graph_file = self.round_path / f"{self.test_type.name}_{self.round_id}.svg"

        self.all_tests : List[Test] = []
        self.current_pos = 0
        self.repetition = 0
        
        # generate all tests
        self.__generate_all_tests()

        # computing the number of tests
        self.number_of_tests = len(self.all_tests) * self.config.repetitions
        
       
    def load_results(self):
        '''
        load the results of the tests, for instance by generating a csv file and loading it into a pandas dataframe
        it can also generate a graph based on the results
        '''
     
        args = [self.config.ior_2_csv, self.round_path, self.csv_file]

        try:
            result = subprocess.run(args, check=True)
            if result.returncode != 0:
                raise Exception(f"Error: Script {self.config.ior_2_csv} finished with a non-zero return code: {result.returncode}")
            # load the csv file into a pandas dataframe
            self.df = pd.read_csv(self.csv_file)
            # generate the graph
            Graphs.generate(self.df, self.graph_file, self.test_type)
            # load the best test
            
            if self.test_type == TestType.COMPUTING:
                gb = self.df.groupby('nodes')
            elif self.test_type == TestType.FILESIZE:
                gb = self.df.groupby('aggregate_filesize')
            elif self.test_type == TestType.STRIPING:
                gb = self.df.groupby('path')
            
            # get the best test
            self.best_bw = 0.0
            for parameter, df_gb in gb:
                if df_gb['bw'].mean() > self.best_bw:
                    self.best_bw = df_gb['bw'].mean()
                    self.best_df = df_gb.copy()
                    self.best_parameter = parameter
            
            # if test_type == FileSize, we need to convert the parameter to MB
            if self.test_type == TestType.FILESIZE:
                self.best_parameter = self.best_parameter / 1024 / 1024

        except subprocess.CalledProcessError as e:
            raise Exception(f"Error: Script execution failed: {e}")
        
        except Exception as e:
            raise Exception(f"Error: {e}")
    
    def __generate_all_tests(self):

        next_test =  Test.create_test(pattern=self.pattern,
                                      file_mode=self.file_mode,
                                      config=self.config,
                                      round_path=self.round_path,
                                      test_parameters=self.initial_parameters)
        
        while next_test is not None:

            # Before the append, we need to create the script for the test
            next_test.build_files()
            # save the test in the list of all tests and create a new test based on the current one
            self.all_tests.append(next_test)
            next_test = Test.from_existing(next_test)
            
            if self.test_type == TestType.COMPUTING:              
                if  next_test.computing < self.config.max_nodes:
                    next_test.test_parameters[TestType.COMPUTING] *= 2
                else:
                    next_test =  None # no more tests to run

            if self.test_type == TestType.FILESIZE:            
                if next_test.volume < self.config.max_volume:
                    next_test.test_parameters[TestType.FILESIZE] += self.config.volume_step                                
                else:
                    next_test = None # no more tests to run        

            if self.test_type == TestType.STRIPING:            
                if next_test.folder_index < len(self.config.stripe_folders) - 1:
                    next_test.test_parameters[TestType.STRIPING] += 1
                else:
                    next_test = None

    def get_best_parameter(self) -> int | float | None:
        '''
        get the best parameter for the current round
        '''
        if self.test_type == TestType.COMPUTING:
            return self.best_parameter
        elif self.test_type == TestType.FILESIZE:
            return self.best_parameter 
        elif self.test_type == TestType.STRIPING:
            folder_path = Path(Path(self.best_parameter).parent.name)
            return self.config.stripe_folders.index(folder_path)
        else:
            raise Exception("Error: Test type not supported")
    
    @staticmethod
    def factory(pattern: Pattern, file_mode: FileMode, config: IOPSConfig, test_type: TestType, initial_parameters: dict):
        '''
        Factory method to create a Round instance based on the search type
        '''
        if config.search_method == SearchType.GREEDY:
            return RoundGreedy(pattern, file_mode, config, test_type, initial_parameters)
        elif config.search_method == SearchType.SMART:
            return RoundSmart(pattern, file_mode, config, test_type, initial_parameters)
        elif config.search_method == SearchType.BINARY:
            return RoundBinary(pattern, file_mode, config, test_type, initial_parameters)
        else:
            raise Exception("Error: Round type not supported")
    
    @abstractmethod
    def next(self, console: Console) -> Test:
        pass
            
    def __repr__(self) -> str:
        return f"Round {self.round_id} \[{self.test_type.name}]\[{self.pattern.name}:{self.file_mode.name}] - up to {self.number_of_tests} tests"



class RoundGreedy(Round):
    def __init__(self, pattern: Pattern, file_mode: FileMode, config: IOPSConfig, test_type: TestType, initial_parameters: dict):
        super().__init__(pattern, file_mode, config, test_type, initial_parameters)
        # randomize the list of tests
        
    
    def next(self, console: Console) -> Test:
        """
        Updates the next Test instance to be executed in the round.
        """                
        if self.current_pos == 0 and self.repetition < self.config.repetitions:
            console.print(f"Repetition {self.repetition + 1}/{self.config.repetitions}", style="bold white on red")

        next_test = None
   
        if self.repetition < self.config.repetitions:
            next_test = self.all_tests[self.current_pos]
            self.current_pos += 1 
            if self.current_pos >= len(self.all_tests):                                                
                self.current_pos = 0
                self.repetition += 1
                random.shuffle(self.all_tests)
        else:            
            # sort the list of tests by test_id
            self.all_tests.sort(key=lambda x: x.test_id)
            self.load_results() # load the results of the entire round
        
        return next_test


class RoundSmart(Round):
    def __init__(self, pattern: Pattern, file_mode: FileMode, config: IOPSConfig, test_type: TestType, initial_parameters: dict):
        super().__init__(pattern, file_mode, config, test_type, initial_parameters)

        self.start_idx = 0
        self.end_idx = len(self.all_tests) - 1
        self.tests_already_run = []
        self.tests_to_run = []

        self.file_size_threshold = 2
        self.tolerance = 0.5
        self.alpha = 10
        
        self.current_test = None
        self.current_repetition = 1
    
    def heuristic(self) -> List | None:
        """
        Search smartly the best test to be executed in the round.
        """

        if self.tests_already_run == []: # start with 3 tests to run
            mid = int((self.end_idx + self.start_idx)) // 2
            return [self.all_tests[self.start_idx],self.all_tests[mid], self.all_tests[self.end_idx]]
        
        # at this point we are sure that we have at least 3 tests runned
        if self.start_idx < self.end_idx:
            mid = int((self.end_idx + self.start_idx)) // 2

            test_left = self.all_tests[self.start_idx]
            test_right = self.all_tests[self.end_idx]
            test_mid = self.all_tests[mid]
            
            max_bw = max(test_left.bw, test_right.bw)

            if self.end_idx - self.start_idx > self.file_size_threshold and abs(test_left.bw - test_right.bw ) > self.tolerance:
                if abs(test_mid.bw - max_bw) > self.tolerance: # if the difference between the mid test and the max bandwidth is greater than the tolerance
                    if test_mid.bw > max_bw:                        
                        max_bw = test_mid.bw
                        self.start_idx = mid
                    else:
                        test_right = test_mid
                        self.end_idx = mid
                else:
                    if abs(test_mid.bw - test_left.bw) < self.alpha: # if the bandwidth did not change much at the left side
                        self.start_idx = mid
                    else:
                        self.end_idx = mid
                if self.start_idx == self.end_idx - 1: # if we have only 2 tests to run and already runned
                    return None
                
                mid = int((self.start_idx + self.end_idx) / 2)
                
                #print(f"Start: {self.start_idx}, Mid: {mid}, End: {self.end_idx}")
                return [self.all_tests[mid]]
            else:
                return None
        else:
            return None

    
    def next(self, console: Console) -> Test:

        if self.current_test is not None and self.current_repetition < self.config.repetitions:
            self.current_repetition += 1    
            return self.current_test
        

        if len(self.tests_to_run) == 0:
            self.tests_to_run = self.heuristic()

        if self.tests_to_run is None:        
            self.load_results()
            next_test =  None
        else:
            next_test = self.tests_to_run.pop(0)
            self.tests_already_run.append(next_test)

        self.current_test = next_test
        self.current_repetition = 1
        return next_test

        
class RoundBinary(Round):
    def __init__(self, pattern: Pattern, file_mode: FileMode, config: IOPSConfig, test_type: TestType, initial_parameters: dict):
        super().__init__(pattern, file_mode, config, test_type, initial_parameters)

        self.left = 0
        self.right = len(self.all_tests) - 1
        self.mid = int((self.left + self.right) / 2)

        self.tests_already_run = []
        self.tests_to_run = []

        self.file_size_threshold = 2
        self.tolerance = 0.5
        self.alpha = 10
        
        self.current_test = None
        self.current_repetition = 1


    def bw_equal(self, bw1: float, bw2: float) -> bool:
        return abs(bw1 - bw2) < self.tolerance

    def bw_greater_than(self, bw1: float, bw2: float) -> bool:
        return bw1 - bw2 > self.tolerance
    
    def bw_less_than(self, bw1: float, bw2: float) -> bool:
        return bw1 - bw2 < self.tolerance
    

    def binary_search(self) -> list:

        if self.tests_already_run == []:
            return [self.all_tests[self.left],self.all_tests[self.mid], self.all_tests[self.right]]

        if self.left < self.right - 1:

            test_left = self.all_tests[self.left]
            test_right = self.all_tests[self.right]
            test_mid = self.all_tests[self.mid]
            
            # case 1: the mid test has a small bandwidth than the left and bigger than the right
            if self.bw_less_than(test_mid.bw,test_left.bw) and self.bw_greater_than(test_mid.bw, test_right.bw):

                self.right = self.mid
                if self.right - self.left == 1:
                    return None
                self.mid = int((self.left + self.right) / 2)
                return [self.all_tests[self.mid]]
            
            # case 2: the mid test has a bigger bandwidth than the left and smaller than the right
            elif self.bw_greater_than(test_mid.bw, test_left.bw) and self.bw_less_than(test_mid.bw, test_right.bw):

                self.left = self.mid
                if self.right - self.left == 1:
                    return None
                self.mid = int((self.left + self.right) / 2)
                return [self.all_tests[self.mid]]
            

            # case 3: the mid test has a bigger bandwidth than the left and bigger than the right or the opposite
            elif (self.bw_greater_than(test_mid.bw, test_left.bw) and self.bw_greater_than(test_mid.bw, test_right.bw)) or (self.bw_less_than(test_mid.bw, test_left.bw) and self.bw_less_than(test_mid.bw, test_right.bw)):

                self.left = int((self.left + self.mid) / 2)
                self.right = int((self.mid + self.right) / 2)
                # mid = int((left + right) / 2)
                return [self.all_tests[self.left], self.all_tests[self.right]]
            else: # case 4: the mid test has the same bandwidth as the left or right
                print("Error: Test not found case to handle")
        else:
            return None
    
    
    def next(self, console: Console) -> Test:

        # if self.current_test is not None and self.current_repetition < self.config.repetitions:
        #     self.current_repetition += 1    
        #     return self.current_test
        

        if len(self.tests_to_run) == 0:
            self.tests_to_run = self.binary_search()

        if self.tests_to_run is None:        
            self.load_results()
            next_test =  None
        else:
            next_test = self.tests_to_run.pop(0)
            self.tests_already_run.append(next_test)

        # self.current_test = next_test
        # self.current_repetition = 1
        return next_test