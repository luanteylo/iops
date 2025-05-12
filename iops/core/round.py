from iops.core.config import IOPSConfig
from iops.core.tests import Test
from iops.core.runner import Runner
from iops.util.generator import Graphs
from iops.util.tags import Parameter, Pattern, FileMode, SearchType, ExecutionMode, Operation


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

    def __init__(self, pattern: Pattern, file_mode: FileMode, operation: Operation, config: IOPSConfig, parameter_name: Parameter, initial_parameters: dict):
        type(self)._id_counter += 1
        self.round_id = self._id_counter
        
        self.pattern = pattern
        self.file_mode = file_mode
        self.operation = operation
        self.config = config
        self.parameter_name = parameter_name        
        self.initial_parameters = initial_parameters

        self.best_bw = None
        self.best_df = None
        self.best_parameter = None
        
        
        self.round_path = self.config.workdir / self.parameter_name.name.lower() / f"round_{self.round_id}"
        # create the directory
        self.round_path.mkdir(parents=True, exist_ok=True)

        # create a list of tests to store all the tests
        self.list_test : List[Test] = []
                
        self.df = None
        self.csv_file = self.round_path / f"{self.parameter_name.name}_{self.round_id}.csv"
        self.graph_file = self.round_path / f"{self.parameter_name.name}_{self.round_id}.svg"

        self.all_tests : List[Test] = []
        self.current_pos = 0
        self.repetition = 0

        # next index set to default stripe index
        self.next_index = self.config.default_stripe
        self.number_of_tests = 0
    
    def load_results(self):
        '''
        load the results of the tests, for instance by generating a csv file and loading it into a pandas dataframe
        it can also generate a graph based on the results
        '''
     
        args = [self.config.ior_2_csv, self.round_path, self.csv_file]

        try:
            if self.config.mode is not ExecutionMode.DEBUG:
                # if not in debug mode, execute the script
                result = subprocess.run(args, check=True)
                if result.returncode != 0:
                    raise Exception(f"Error: Script {self.config.ior_2_csv} finished with a non-zero return code: {result.returncode}")        
                # load the csv file into a pandas dataframe
                self.df = pd.read_csv(self.csv_file)    
            else: 
                # DEBUG MODE
                self.df = pd.DataFrame()
                for test in self.all_tests:
                    if test.number_of_executions > 0:
                        self.df = pd.concat([self.df, test.df])                        
                # if in regular mode, we check if the csv file do not exist than we generate it by reading the all csv files in the round folder
                #if not self.csv_file.exists():
                    # get all csv files in the round folder (recursive considering all folders)
                #    csv_files = list(self.round_path.rglob("*.csv"))                    
                    # concatenate the csv files
                #    df = pd.concat([pd.read_csv(f) for f in csv_files])
                    # save the csv file
                self.df.to_csv(self.csv_file, index=False)
                    
                    
            
            # generate the graph
            Graphs.generate(self.df, self.graph_file, self.parameter_name)
            # load the best test
            
            if self.parameter_name == Parameter.COMPUTING:
                gb = self.df.groupby('nodes')
            elif self.parameter_name == Parameter.FILESIZE:
                gb = self.df.groupby('aggregate_filesize')
            elif self.parameter_name == Parameter.STRIPING:
                gb = self.df.groupby('path')
            elif self.parameter_name == Parameter.NUM_PROCESSES: # num_processes test
                gb = self.df.groupby('clients_per_node')
            
            # get the best test
            self.best_bw = 0.0
            for parameter, df_gb in gb:
                if df_gb['bw'].mean() > self.best_bw:
                    self.best_bw = df_gb['bw'].mean()
                    self.best_df = df_gb.copy()
                    self.best_parameter = parameter
            
            # if test_type == FileSize, we need to convert the parameter to MB
            if self.parameter_name == Parameter.FILESIZE:
                self.best_parameter = self.best_parameter / 1024 / 1024

        except subprocess.CalledProcessError as e:
            raise Exception(f"Error: Script execution failed: {e}")
        
        except Exception as e:
            raise Exception(f"Error: {e}")
    
    def build_tests(self):
        '''
        Build all tests of the current round and generate the files
        '''

        next_test =  Test.create_test(pattern=self.pattern,
                                      file_mode=self.file_mode,
                                      config=self.config,
                                      round_path=self.round_path,
                                      test_parameters=self.initial_parameters,
                                      operation=self.operation)
        
        while next_test is not None:

            # Before the append, we need to create the script for the test
            next_test.build_files()
            # save the test in the list of all tests and create a new test based on the current one
            self.all_tests.append(next_test)
            next_test = Test.from_existing(next_test)
            
            if self.parameter_name == Parameter.COMPUTING:              
                if  next_test.computing < self.config.max_nodes:
                    next_test.test_parameters[Parameter.COMPUTING] *= 2
                else:
                    next_test =  None # no more tests to run

            if self.parameter_name == Parameter.FILESIZE:            
                if next_test.volume < self.config.max_volume:
                    next_test.test_parameters[Parameter.FILESIZE] += self.config.volume_step                                
                else:
                    next_test = None # no more tests to run        

            if self.parameter_name == Parameter.STRIPING:
                self.next_index = (self.next_index + 1) % len(self.config.stripe_folders)
                
                if self.next_index != self.config.default_stripe:
                    next_test.test_parameters[Parameter.STRIPING] = self.config.get_stripe_folder(self.next_index)    
                else:
                    next_test = None # no more tests to run
        # computing the number of tests
        self.number_of_tests = len(self.all_tests) * self.config.repetitions

    def get_best_parameter(self) -> int | float | None:
        '''
        get the best parameter for the current round
        '''
        if self.parameter_name == Parameter.COMPUTING:
            return self.best_parameter
        elif self.parameter_name == Parameter.FILESIZE:
            return self.best_parameter 
        elif self.parameter_name == Parameter.STRIPING:
            # get only the path (remove the file)
            folder_path = Path(Path(self.best_parameter).parent)
            return folder_path
        elif self.parameter_name == Parameter.NUM_PROCESSES:
            return self.best_parameter
        else:
            raise Exception("Error: Test type not supported")
    
    @staticmethod
    def factory(*args, **kwargs):
        '''
        Factory method to create a Round instance based on the search type
        '''
        pattern = kwargs.get('pattern')
        file_mode = kwargs.get('file_mode')
        operation = kwargs.get('operation')
        config = kwargs.get('config')        
        parameter_name = kwargs.get('parameter_name')
        initial_parameters = kwargs.get('initial_parameters')
        
        if config.search_method == SearchType.GREEDY:
            return RoundGreedy(pattern=pattern, 
                               file_mode=file_mode, 
                               operation=operation, 
                               config=config, 
                               parameter_name=parameter_name, 
                               initial_parameters=initial_parameters)
        
        elif config.search_method == SearchType.BINARY:
            return RoundBinary(pattern=pattern, 
                               file_mode=file_mode, 
                               operation=operation, 
                               config=config, 
                               parameter_name=parameter_name, 
                               initial_parameters=initial_parameters)        
        else:
            raise Exception("Error: Round type not supported")
    
    @abstractmethod
    def next(self, console: Console) -> Test:
        pass

    def build_read_round(self):
        '''
        Rebuild the tests for read operation
        '''
        type_class = type(self)
        new_round = type_class(pattern=self.pattern, 
                               file_mode=self.file_mode,  
                               operation=Operation.READ,
                               config=self.config, 
                               parameter_name=self.parameter_name, 
                               initial_parameters=self.initial_parameters)
        
        
        for test in self.all_tests:
            if test.was_executed or self.config.mode == ExecutionMode.DEBUG:
                # create a new test based on the current one
                test_read = Test.create_test(pattern=self.pattern,
                                            file_mode=self.file_mode,
                                            config=self.config,
                                            round_path=new_round.round_path,
                                            test_parameters=test.test_parameters,
                                            operation=Operation.READ)
                
                test_read.set_input_file(test.output_file)
                test_read.build_files()
                

            new_round.all_tests.append(test_read)
        
        new_round.number_of_tests = len(new_round.all_tests) * self.config.repetitions
        return new_round
        
    def delete_readed_files(self):
        for test in self.all_tests:
            test.output_file.unlink()

    def completed_message(self) -> str:
        return f"Round {self.round_id} completed successfully.\nBest parameter for {self.parameter_name.name}: {self.best_parameter}"
        
    def run(self):
        '''
        Run the tests of the current round
        '''
        Runner.run(self)     
        
            
    def __repr__(self) -> str:
        return f"Round {self.round_id} \[{self.parameter_name.name}]\[{self.pattern.name}:{self.file_mode.name}]\[{self.operation.name}] - up to {self.number_of_tests} tests"



class RoundGreedy(Round):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
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
        
class RoundBinary(Round):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.left = 0
        self.right = len(self.all_tests) - 1
        self.mid = int((self.left + self.right) / 2)

        self.tests_already_run = []
        self.tests_to_run = []
        self.repetition = 1
        
    def binary_search(self) -> list:
        if self.tests_already_run == []:
            return [self.all_tests[self.left],self.all_tests[self.mid], self.all_tests[self.right]]

        if self.left < self.right - 1:
            test_left = self.all_tests[self.left]
            test_right = self.all_tests[self.right]
            test_mid = self.all_tests[self.mid]
            
            # case 1: the mid test has a small bandwidth than the left and bigger than the right or equal
            if test_left >= test_mid and test_left > test_right:
                self.right = self.mid
                if self.right - self.left == 1:
                    return None
                self.mid = int((self.left + self.right) / 2)
                return [self.all_tests[self.mid]]
            
            # case 2: the mid test has a bigger bandwidth than the left and smaller than the right
            elif test_right >= test_mid and test_right > test_left:
                self.left = self.mid
                if self.right - self.left == 1:
                    return None
                self.mid = int((self.left + self.right) / 2)
                return [self.all_tests[self.mid]]
            # case 3: the mid test has a bigger bandwidth than the left and bigger than the right or the opposite
            else:
                if (self.left - self.mid == 1) or  (self.right - self.mid == 1):
                    return None
                self.left = int((self.left + self.mid) / 2)
                self.right = int((self.mid + self.right) / 2)                
                return [self.all_tests[self.left], self.all_tests[self.right]]            
        else:
            return None
    
    def next(self, console: Console) -> Test:

        if len(self.tests_to_run) == 0:                       
            self.tests_to_run = self.binary_search()      
          

        # check if we did all repetitions
        if self.tests_to_run is None and self.repetition < self.config.repetitions:
            self.repetition += 1
            self.left = 0
            self.right = len(self.all_tests) - 1            
            self.mid = int((self.left + self.right) / 2)
            self.tests_already_run = []
            self.tests_to_run = []           
            self.tests_to_run = self.binary_search()
            console.print(f"Repetition {self.repetition}/{self.config.repetitions}", style="bold white on red")
        
            

        if self.tests_to_run is None:        
            self.load_results()
            next_test =  None
        else:
            next_test = self.tests_to_run.pop(0)
            self.tests_already_run.append(next_test)
  
        return next_test