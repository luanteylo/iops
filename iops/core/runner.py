
from iops.core.tests import Test
from iops.core.round import Round
from iops.util.submitter import Submitter
from iops.util.tags import  jobManager, ExecutionMode

import sys
import time
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.panel import Panel



console = Console()       

# Define the style of the progress bar
progress_columns = [
    TextColumn("[bold green]{task.fields[round_id]}[/]", justify="left"),
    BarColumn(bar_width=20, complete_style="green3", finished_style="bold green"),
    TextColumn("[progress.percentage]"),
    TaskProgressColumn(),
    TextColumn("({task.completed}/{task.total} tests)")
]

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
            else:
                # load the results of the test
                test.load_results() # load the results of the test
                
            

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
                    test = round.next(console)  # Move to the next test in the round.            
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
                # stop the excuting jobs 
                Submitter.stop_slurm()

            # when a ctrl+c is pressed, stop the execution of tests
            sys.exit(1)

        except Exception as e:
            # Handle general exceptions.
            raise e

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
        


      