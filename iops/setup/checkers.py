import logging
import subprocess
from rich.console import Console
from argparse import Namespace
from iops.setup.iops_config import IOPSConfig
from rich.traceback import Traceback
from rich.traceback import install

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
        try:
            # Check if 'ior' binary is available
            subprocess.run(["ior", "--help"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            console.print("[bold green]Ready to Go!")
            return True
        except subprocess.CalledProcessError as e:
            console.print("[bold red]Error:[/bold red]", e)
            console.print("[bold yellow]Warning:[/bold yellow] If you are able to run 'ior -h' from the command line, it may actually be working.")
            console.print("[bold yellow]Warning:[/bold yellow] Versions more recent of IOR return a non-zero exit code when running  'ior -h' which messes up the IOR installation check.")
        except FileNotFoundError:
            console.print("[bold red]Error:[/bold red] ior binary not found. Make sure it is installed and available in $PATH.")
        
        return False
