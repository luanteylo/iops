import subprocess
from rich.console import Console
from iops.core.config import IOPSConfig
from rich.traceback import Traceback

import sys


console = Console()

class Checker:

    @staticmethod
    def check_ini_file(config_path : str, debug : bool = False) -> bool:
        '''
        Check if the ini file is valid.
        '''
        console.print(f"[bold green]Checking configuration file {config_path}...[/bold green]")
        try:
            IOPSConfig(config_path)
            console.print("[bold green]Configuration file is valid!")
            return True
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            console.print("[bold red]Error:[/bold red] [white]{}[/white]".format(exc_value))
            if debug:
                console.print(Traceback.from_exception(exc_type, exc_value, exc_traceback))
            return False

    @staticmethod
    def check_ior_installation() -> bool:
        '''
        Check if IOR is installed and available in $PATH.
        '''
        console = Console()
        try:
            # Run 'ior -h' and ignore the return code
            result = subprocess.run(["ior", "-h"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Print a success message if the command executes (regardless of return code)
            console.print("[bold green]IOR is installed.[/bold green]")
            return True
        except FileNotFoundError:
            # Handle the case where 'ior' is not found in the path
            console.print("[bold red]Error: 'ior' binary not found. Make sure it is installed and available in $PATH.[/bold red]")
            return False
        except Exception as e:
            # Handle any other exception that could occur
            console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
            return False

    @staticmethod
    def check_mpi() -> bool:
        '''
        Check if MPI is installed and available in $PATH.
        '''
        console = Console()
        try:
            # Run 'mpirun -h' and ignore the return code
            result = subprocess.run(["mpirun", "-h"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Print a success message if the command executes (regardless of return code)
            console.print("[bold green]MPI is installed.[/bold green]")
            return True
        except Exception as e:
            # Handle any other exception that could occur
            console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")
            return False
        # console.print("[bold red] Error: MPI is not installed.[/bold red]")