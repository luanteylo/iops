import configparser
import re
import sys 
from rich.console import Console
from rich.traceback import Traceback
from rich.traceback import install
from pathlib import Path

from iops.setup.pfs import FileSystems

install(show_locals=True)

console = Console()


VALID_FILE_SYSTEMS = {"lustre", "beegfs", "local"}  # Add other allowed file systems if needed
VALID_MODES = {"fast", "complete"}  # Add other allowed modes if needed
VALID_JOB_MANAGERS = {"slurm", "none"}  # Add other allowed job managers if needed


class IOPSConfig:
    def __init__(self, config_path: str):
        self.config = configparser.ConfigParser()
        self.config.read(config_path)

        self.errors = []
        
        self.load_nodes()
        self.load_storage()
        self.load_execution()
        self.load_templates()

        if self.errors:
            for error in self.errors:
                console.print("[bold red]Error:[/bold red] [white]{}[/white]".format(error))
            raise Exception("Configuration file is invalid. Please fix the errors above.")


    def __get(self, section, key):
        value = self.config.get(section, key)       
        if "#" in value:
            value = value.split("#")[0].strip()
        return value
        
    def load_nodes(self):
        self.max_nodes = int(self.__get("nodes", "max_nodes"))
        self.processes_per_node = int(self.__get("nodes", "processes_per_node"))
        
        if self.max_nodes < 0 or self.processes_per_node < 0:
            self.errors.append(f"Number of nodes and processes per node need to be greater than zero.")

    def load_storage(self):
        self.benchmark_output = Path(self.__get("storage", "benchmark_output"))
        self.file_system = self.__get("storage", "file_system")        
        self.max_volume = int(self.__get("storage", "max_volume"))
        stripe_folders_str =  self.__get("storage", "output_stripe_folders")
        
        if self.file_system not in VALID_FILE_SYSTEMS:
            self.errors.append(f"Invalid file_system: '{self.file_system}'. Allowed values are {', '.join(VALID_FILE_SYSTEMS)}.\nDid you remove the '|' character from the .ini file?")
            return       

        fs = FileSystems(self.file_system, self.benchmark_output)

        if not fs.check_path():
            self.errors.append(f"Invalid path: '{self.benchmark_output}'")
            #raise Exception(f"Invalid path: '{self.path}'. Path does not exist or is not a mount point.")
        
        # check if the max_volume is power of 2
        if self.max_volume > 0 and (self.max_volume & (self.max_volume - 1)) != 0:
            self.errors.append(f"Invalid max_volume: '{self.max_volume}'. max_volume must be a power of 2.")
        
        # check stripe_folders
        # Parse and load the modules
        if stripe_folders_str.lower() == 'none':
            self.stripe_folders = None
        else:
            self.stripe_folders = [stripe.strip() for stripe in stripe_folders_str.split(',')]
            # check if the stripe_folders are valid
            for folder in self.stripe_folders:
                if not fs.check_path(folder):
                    self.errors.append(f"Invalid path for stripe folder: '{self.benchmark_output / folder}'")
            #raise Exception(f"Invalid path: '{self.path}'. Path does not exist or is not a mount point.")
        
    def load_execution(self):        
        self.mode = self.__get("execution", "mode").lower()
        self.job_manager = self.__get("execution", "job_manager").lower()
        slurm_constraint_str = self.__get("execution", "slurm_constraint")
        modules_str = self.__get("execution", "modules")
        self.workdir = Path(self.__get("execution", "workdir"))
        self.repetitions = int(self.__get("execution", "repetitions"))
        

        if self.mode not in VALID_MODES:
            self.errors.append(f"Invalid mode: '{self.mode}'. Allowed values are '{', '.join(VALID_MODES)}'.\nDid you remove the '|' character from the .ini file?")
            #raise Exception(f"Invalid mode: '{self.mode}'. Allowed values are '{', '.join(VALID_MODES)}'.\nDid you remove the '|' character from the .ini file?")
        
        if self.job_manager not in VALID_JOB_MANAGERS:
            self.errors.append(f"Invalid job_manager: '{self.job_manager}'. Allowed values are '{', '.join(VALID_JOB_MANAGERS)}'.\nDid you remove the '|' character from the .ini file?")
        
        if self.job_manager == "none":
            self.job_manager = None
        
        # Parse and load the modules
        if modules_str.lower() == 'none':
            self.modules = None
        else:
            self.modules = [module.strip() for module in modules_str.split(',')]
        
        # Parse the slurm_constraint
        if slurm_constraint_str.lower() == 'none':
            self.slurm_constraint = None
        else:
            self.slurm_constraint = [constraint.strip() for constraint in slurm_constraint_str.split(',')]

        if not self.workdir.is_dir():
            self.errors.append(f"Invalid path for workdir folder: '{self.workdir}'")

        if self.repetitions <= 0:
            self.errors.append(f"The number of repetitions must be greater than zero.")        

    def load_templates(self):
        slurm_template_str = self.__get("template", "slurm_template")
        self.ior_2_csv = Path(self.__get("template", "ior_2_csv"))
        self.report_template = Path(self.__get("template", "report_template"))        

        # check template file
        if slurm_template_str.lower() == 'none':
            self.slurm_template = None
        else:
            self.slurm_template = Path(slurm_template_str)
            # check if file exist
            if not self.slurm_template.is_file():
                self.errors.append(f"File not found: '{self.slurm_template}'")
            
        if self.job_manager == 'slurm' and self.slurm_template == None:
            self.errors.append(f"When using slurm, a template file needs to be provided.")
        
        if not self.ior_2_csv.is_file():
            self.errors.append(f"File not found: '{self.ior_2_csv}'")
        
        if not self.report_template.is_file():
            self.errors.append(f"File not found: '{self.report_template}'")
       
        
    def parse_nodes(self, nodes_str):        
        nodes_list = []
        patterns = re.findall(r"([a-zA-Z0-9]+)\[([^\]]+)\]|([a-zA-Z0-9]+)", nodes_str)
        
        for pattern in patterns:
            prefix, range_str, single_node = pattern
            if prefix:
                # Split by comma inside the range
                for subrange in range_str.split(","):
                    subrange = subrange.strip()
                    
                    # Check if the subrange is a simple number or a range
                    if "-" in subrange:
                        start, end = map(int, subrange.split("-"))
                        for i in range(start, end + 1):
                            nodes_list.append(f"{prefix}{i}")
                    else:
                        nodes_list.append(f"{prefix}{subrange}")
            else:
                nodes_list.append(single_node)
        return nodes_list
    