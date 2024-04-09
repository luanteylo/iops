from iops.core.config import IOPSConfig
from iops.util.tags import TestType


from typing import List, Optional, Any
from rich.console import Console
from typing import Union
import time

console = Console()       


class Round:
    """
    This class represents a round and receives a dictionary with a set of static parameters and a test type.
    According to the test type, the round will be built. For example, if the test_type is `COMPUTING`,
    the round will be constructed by varying the number of computing nodes.

    This class exposes the function `next`, which returns the next test or `None`, in case the round has ended.
    """

    def __init__(self, parameters: dict, test_type: TestType):
        self.parameters = parameters
        self.test_type = test_type
        self.current_test = self.parameters

    def next(self) -> Union[dict, None]: # unsupported operand type(s) for |: 'type' and 'NoneType'
        """
        Returns the next test; otherwise, returns None.
        """
        if self.current_test['computing_nodes'] < 10:
            self.current_test['computing_nodes'] += 1
            return self.current_test
        else:
            return None
            
        


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
                test = round.next()  # Retrieve the next test.
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
        


      