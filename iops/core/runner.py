import sys
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
from rich.panel import Panel
import time
import random

from iops.core.tests import Test


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
    def wait(start_time: int, end_time: int) -> int:
        wait_time = start_time
        if start_time !=  end_time:
             wait_time =  random.randrange(start_time, end_time)                            
        
        time.sleep(wait_time)
        return wait_time


    @staticmethod
    def _run(test: Test) -> None:
        """
        Executes a given test by building the appropriate batch file and submitting it for execution.
        
        Parameters:
        - test (Any): A set of pre-defined parameters that describe the test to be executed.
        """        
        console.print(f"{test}")
        # running the test
        job_id, result = test.config.job_manager.submit(test.batch_file)  # Submit the batch file for execution.
        
        # wait for the job to finish
        if job_id:
            #status = test.config.job_manager.wait(job_id)  # Wait for the job to finish.
            while True:
                status = test.config.job_manager.get_status(job_id)  # Get the job status.
                console.print(f"\t\tJob ID: {job_id}  Status: {status}.")
                if status not in [test.config.job_manager.STATUS_RUNNING, 
                                  test.config.job_manager.STATUS_PENDING]:
                    break
                console.print(f"\t\tWaiting {test.config.status_check_delay} seconds for the job to finish.")
                time.sleep(test.config.status_check_delay)
            
            test.load_results() # load the results of the test            
        else:
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
    def run(round):
        """
        Executes the tests within a given Round, sequentially calling the next test until all tests are completed.
     
        Parameters:
        - round (Round): The Round object containing the tests to be executed.

        Returns:
        - Round: The same Round object, after all tests have been executed.
        """

        try:            
            console.print(Panel(f"{round}", style="bold green", expand=True))

            # Create a progress bar for the round using the rich library
            with Progress(*progress_columns, console=console) as progress:
                # Start a task with specific metadata for the round and total number of tests
                round_task = progress.add_task("[green]Round", round_id=f"Round {round.round_id}",
                                            total=round.number_of_tests)

                while True:
                    test = round.next(console)  # Move to the next test in the round.            
                    
                    if test:
                        Runner._run(test)  # Execute the test using the static method.
                        waited_time = Runner.wait(round.config.wait_start, round.config.wait_end)
                        if waited_time > 0:
                            console.print(f"\t[yellow]Waited {waited_time} seconds before running the next test")
                        progress.update(round_task, advance=1)  # Update the progress bar.
                    else:
                        break  # Exit the loop if there are no more tests.

        except KeyboardInterrupt:
            # Handle user interruption.
            # Assuming console is a logging or output object you've defined elsewhere
            console.print("[bold red]Aborting test due to user interruption.")
            console.print("[bold yellow]Warning:[/bold yellow] You may have an ongoing job in the job manager.")

            # when a ctrl+c is pressed, stop the execution of tests
            sys.exit(1)

        except Exception as e:
            # Handle general exceptions.
            raise e
        


        


      