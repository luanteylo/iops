from iops.core.config import IOPSConfig
from iops.core.tests import Test
from iops.util.generator import Graphs
from iops.util.submitter import Submitter
from iops.util.tags import TestType, jobManager, ExecutionMode, Pattern, Operation

import sys
import pandas as pd
import subprocess
import random
from typing import List
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.panel import Panel
import time



console = Console()       

# Define the style of the progress bar
progress_columns = [
    TextColumn("[bold green]{task.fields[round_id]}[/]", justify="left"),
    BarColumn(bar_width=20, complete_style="green3", finished_style="bold green"),
    TextColumn("[progress.percentage]"),
    TaskProgressColumn(),
    TextColumn("({task.completed}/{task.total} tests)")
]


class Round:
    """
    Represents a round of tests, generating and managing Test instances
    based on the configured test type.
    """
    _id_counter = 0

    def __init__(self, config: IOPSConfig, test_type: TestType, round_parameters: dict):
        type(self)._id_counter += 1
        self.round_id = self._id_counter
        
        self.config = config
        self.test_type = test_type        
        self.round_parameters = round_parameters
        
        self.round_path = self.config.workdir / self.test_type.name.lower() / f"round_{self.round_id}"
        # create the directory
        self.round_path.mkdir(parents=True, exist_ok=True)

        # create a list of tests to store all the tests
        self.list_test : List[Test] = []
                
        self.df = None
        self.csv_file = self.round_path / f"{self.test_type.name}_{self.round_id}.csv"
        self.graph_file = self.round_path / f"{self.test_type.name}_{self.round_id}.svg"

        self.all_tests : List[Test] = []
        self.__current_pos = 0
        self.__repetition = 0
        
        # generate all tests
        self.__generate_all_tests()

        # computing the number of tests
        self.number_of_tests = len(self.all_tests) * self.config.repetitions
        
       
    def __load_results(self):
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

        except subprocess.CalledProcessError as e:
            raise Exception(f"Error: Script execution failed: {e}")
        
        except Exception as e:
            raise Exception(f"Error: {e}")
    @property
    def get_computing_nodes(self):
        '''
        get the computing nodes from the previous round
        '''
        return self.df.loc[self.df['bw'].idxmax(), 'nodes']

    @property
    def get_volume(self):
        '''
        get the volume from the previous round
        '''
        return self.df.loc[self.df['bw'].idxmax(), 'volume']
    
    

    def __generate_all_tests(self):

        next_test =  Test.create_test(pattern=Pattern.SEQUENTIAL,
                                      operation=Operation.WRITE,
                                      config=self.config,
                                      round_path=self.round_path,
                                      test_parameters=self.round_parameters)
        
        while next_test is not None:

            # Before the append, we need to create the script for the test
            next_test.build_files()
            # save the test in the list of all tests and create a new test based on the current one
            self.all_tests.append(next_test)
            next_test = Test.from_existing(next_test)
            
            if self.test_type == TestType.COMPUTING:              
                if  next_test.computing < self.config.max_nodes:
                    next_test.test_parameters['computing'] *= 2
                else:
                    next_test =  None # no more tests to run

            if self.test_type == TestType.FILESIZE:            
                if next_test.volume < self.config.max_volume:
                    next_test.test_parameters['volume'] += 512                                
                else:
                    next_test = None # no more tests to run        

            if self.test_type == TestType.STRIPING:            
                if next_test.folder_index < len(self.config.stripe_folders) - 1:
                    next_test.test_parameters['folder_index'] += 1
                else:
                    next_test = None
        # randomize the list of tests
        random.shuffle(self.all_tests)
            

    def next(self) -> Test | None:
        """
        Updates the next Test instance to be executed in the round.
        """
                
        if self.__current_pos == 0 and self.__repetition < self.config.repetitions:
            console.print(f"Repetition {self.__repetition + 1}/{self.config.repetitions}", style="bold white on red")

        next_test = None
        if self.__repetition < self.config.repetitions:
            next_test = self.all_tests[self.__current_pos]
            self.__current_pos += 1 
            if self.__current_pos >= len(self.all_tests):                                                
                self.__current_pos = 0
                self.__repetition += 1
                random.shuffle(self.all_tests)
        else:            
            self.__load_results()
        
        return next_test
            
    def __repr__(self) -> str:
        return f"Round {self.round_id} \[{self.test_type.name}]"



class Runner:
    """
    The Runner class orchestrates the execution of tests defined within a Round.
    It provides static methods to execute individual tests based on predefined parameters and manages the overall test execution flow,
    ensuring all tests within a round are run sequentially until completion, without requiring an instance of the class.
    """

    @staticmethod
    def _run(test: Test) -> None:
        """
        Executes a given test by building the appropriate batch file and submitting it for execution.
        
        Parameters:
        - test (Any): A set of pre-defined parameters that describe the test to be executed.
        """        
        console.print(f"{test}")
        # running the test
        if test.config.mode != ExecutionMode.DEBUG:
            result = Submitter.submit(test.batch_file, test.config.job_manager)               
            if result.returncode != 0:                
                # Decode the output only once
                decoded_stderr = result.stderr.decode('utf-8')
                decoded_stdout = result.stdout.decode('utf-8')

                # Print a clear, styled message about the test failure
                console.print(f"\tError: Test: {test.test_id} Failed", style="bold red")

                # Adjusting the panel size by setting a width and changing the border style
                panel_width = 80  # Adjust the width as needed
                stderr_panel = Panel(decoded_stderr, title="stderr", subtitle=f"Test ID: {test.test_id}", style="bold red", width=panel_width, border_style="red")
                stdout_panel = Panel(decoded_stdout, title="stdout", subtitle=f"Test ID: {test.test_id}", style="bold green", width=panel_width, border_style="green")

                console.print(stderr_panel, justify="center")
                console.print(stdout_panel, justify="center")


                # Stopping execution message
                console.print("Stopping the execution of the tests", style="bold red")

                # Exit the script
                sys.exit(1)
            

    @staticmethod
    def run(round: Round) -> Round:
        """
        Executes the tests within a given Round, sequentially calling the next test until all tests are completed.
     
        Parameters:
        - round (Round): The Round object containing the tests to be executed.

        Returns:
        - Round: The same Round object, after all tests have been executed.
        """
        start_time = time.time()

        try:            
            console.print(Panel(f"{round}", style="bold green", expand=True))

            # Create the Progress instance with the defined columns
            with Progress(*progress_columns, console=console) as progress:
                # Start a task with specific metadata for the round and total number of tests
                round_task = progress.add_task("[green]Round", round_id=f"Round {round.round_id}",
                                            total=round.number_of_tests)

                while True:

                    test = round.next()  # Move to the next test in the round.            
                    if test:
                        Runner._run(test)  # Execute the test using the static method.
                    else:
                        break  # Exit the loop if there are no more tests.
                        
                    progress.update(round_task, advance=1)  # Update the progress bar.

        except KeyboardInterrupt:
            # Handle user interruption.
            # Assuming console is a logging or output object you've defined elsewhere
            console.print("[bold red]Aborting test due to user interruption.")
            console.print("[bold yellow]Warning:[/bold yellow] You may have an ongoing job in the job manager.")

            # check if there is a test running and stop it
            if round.config.job_manager == jobManager.SLURM:
                # stop the test
                Submitter.stop_slurm()

            # when a ctrl+c is pressed, stop the execution of tests
            sys.exit(1)

            # response = input("Press 'n' to move to the next test, or 'q' to quit: ")
            # if response.lower() == 'n':
            #     # Skip to the next test
            #     pass

        except Exception as e:
            # Handle general exceptions.
            console.print(f"[bold red]Error:[/bold red] {str(e)}")

        # console.print(f"List of tests: {round.list_test}")

        end_time = time.time()
        execution_time = end_time - start_time  
        formatted_time = Runner.__format_time(execution_time) 
        console.print(f"[bold green]Round Execution Time:[/bold green] {formatted_time}")

        return round

    @staticmethod
    def __format_time(seconds: float) -> str:
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours} hours, {minutes} minutes, and {seconds} seconds"
        


      