from iops.core.config import IOPSConfig
from iops.util.tags import TestType


from typing import List, Optional, Any
from rich.console import Console
from typing import Union
import time
from pathlib import Path

console = Console()       


class TestIOR:
    """
    Represents a single IOR test, containing the parameters required to execute the test.
    """

    def __init__(self, volume: int, folder_index: int, computing : int, config: IOPSConfig):
        """
        Initializes a new instance of a test.
        
        :param volume: The volume parameter for the test.
        :param folder: The folder parameter for the test.
        :param computing: The computing parameter for the test.
        """
        self.volume = volume
        self.folder_index = folder_index
        self.computing = computing

        self.config = config
    
    def __get_ior_command(self) -> str:
        pass

    def generate_batch_file(self, file_path: Path) -> Path:
        pass    

    def __repr__(self):
        return f"<Test volume={self.volume}, folder_index={self.config.stripe_folders[self.folder_index]}, computing={self.computing}>"

class Round:
    """
    Represents a round of tests, generating and managing Test instances
    based on the configured test type.
    """

    def __init__(self,  volume: int, folder_index: int,  computing: int, config: IOPSConfig, test_type: TestType):
        self.round_id = None # <--- Add a unique identifier for the round

        self.test_type = test_type
        self.config = config

        self.current_test = TestIOR(volume=volume,
                                 folder_index=folder_index, 
                                 computing=computing,
                                 config=config)
        
        self.__generate_directory_structure()


    def __generate_directory_structure(self) -> None:
        '''
        this method generates a directory structure that represents a round. The folder is created in the workdir directory and has the following structure:

        workdir/<round_id>_<test_type>/
            - exec_01/
            - exec_02/
            - exec_03/
            ...
            - exec_<max_exec>/
        '''
        pass

    def next(self) -> None: 
        """
        Generates the next Test instance based on the test type and current state
        """
        # copy the current test and update it
        next_test : TestIOR = self.current_test
        
        if self.test_type == TestType.COMPUTING:              
            if  next_test.computing < self.config.max_nodes:
                next_test.computing += 1
            else:
                next_test =  None # no more tests to run
                
        if self.test_type == TestType.FILESIZE:            
            if next_test.volume < self.config.max_volume:
                next_test.volume += 1073741824                                
            else:
                next_test = None # no more tests to run        

        if self.test_type == TestType.STRIPING:            
            if next_test.folder_index < len(self.config.stripe_folders) - 1:
                next_test.folder_index += 1
            else:
                next_test = None
        
        self.current_test = next_test
        return next_test

    def __repr__(self) -> str:
        return f"Round test_type={self.test_type}, current_test={self.current_test}"



class Runner:
    """
    The Runner class orchestrates the execution of tests defined within a Round.
    It provides static methods to execute individual tests based on predefined parameters and manages the overall test execution flow,
    ensuring all tests within a round are run sequentially until completion, without requiring an instance of the class.
    """

    @staticmethod
    def _run(test: dict) -> None:
        """
        Executes a given test by building the appropriate batch file and submitting it for execution.
        
        Parameters:
        - test (Any): A set of pre-defined parameters that describe the test to be executed.
        """
        console.print(f"[bold green]Run Test:[/bold green] {test}")

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
            while True:

                test = round.next()                

                if test:
                    Runner._run(test)  # Execute the test using the static method.
                else:
                    break  # Exit the loop if there are no more tests.

                

        except KeyboardInterrupt:
            # Handle user interruption.
            # Assuming console is a logging or output object you've defined elsewhere
            console.print("[bold red]Aborting test due to user interruption.")
            console.print("[bold yellow]Warning:[/bold yellow] You may have an ongoing job in the job manager.")
            error = True

        except Exception as e:
            # Handle general exceptions.
            console.print(f"[bold red]Error:[/bold red] {str(e)}")
            error = True

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
        


      