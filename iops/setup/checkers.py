import logging
import subprocess
from rich.console import Console

console = Console()

class Checker:

    @staticmethod
    def check_ior_installation() -> bool:
        '''
        Check if IOR is installed and available in $PATH.
        '''
        try:
            # Check if 'ior' binary is available
            subprocess.run(["ior", "-h"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            console.print("[bold green]Ready to Go!")
            return True
        except subprocess.CalledProcessError as e:
            console.print("[bold red]Error:[/bold red]", e)
            console.print("[bold yellow]Warning:[/bold yellow] If you are able to run 'ior -h' from the command line, it may actually be working.")
            console.print("[bold yellow]Warning:[/bold yellow] Versions more recent of IOR return a non-zero exit code when running  'ior -h' which messes up the IOR installation check.")
        except FileNotFoundError:
            console.print("[bold red]Error:[/bold red] ior binary not found. Make sure it is installed and available in $PATH.")
        
        return False
