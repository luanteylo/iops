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
        nodes_str = self.__get("nodes", "nodes")
        self.nodes = self.parse_nodes(nodes_str)
        self.max_nodes = int(self.__get("nodes", "max_nodes"))
        self.max_processes_per_node = int(self.__get("nodes", "max_processes_per_node"))

        if len(self.nodes) != self.max_nodes:
            self.errors.append(f"Number of nodes in nodes parameter {self.nodes} ({len(self.nodes)}) does not match max_nodes ({self.max_nodes})")

        #assert len(self.nodes) == self.max_nodes, f"Number of nodes in nodes parameter {self.nodes} ({len(self.nodes)}) does not match max_nodes ({self.max_nodes})"
        

    def load_storage(self):
        self.path = Path(self.__get("storage", "path"))
        self.file_system = self.__get("storage", "file_system")

        
        self.max_ost = int(self.__get("storage", "max_ost"))
        self.default_stripe_count = int(self.__get("storage", "default_stripe_count"))
        self.default_stripe_size = int(self.__get("storage", "default_stripe_size"))
        self.max_volume = int(self.__get("storage", "max_volume"))   
        
        if self.file_system not in VALID_FILE_SYSTEMS:
            self.errors.append(f"Invalid file_system: '{self.file_system}'. Allowed values are {', '.join(VALID_FILE_SYSTEMS)}.\nDid you remove the '|' character from the .ini file?")
            return
     

        if self.file_system.lower() == "local":
            console.print(f"[bold yellow]Warning:[/bold yellow] File system is local. Overriding max_ost ({self.max_ost}), default_stripe_count ({self.default_stripe_count}) and default_stripe_size ({self.default_stripe_size}) to 1.")            
            self.max_ost = 1
            self.default_stripe_count = 1
            self.default_stripe_size = 1      

        fs = FileSystems(self.file_system, self.path)

        if not fs.check_path():
            self.errors.append(f"Invalid path: '{self.path}'")
            #raise Exception(f"Invalid path: '{self.path}'. Path does not exist or is not a mount point.")

        ost_count = fs.get_ost_count()
        if ost_count < self.max_ost:
            self.errors.append(f"Invalid max_ost: '{self.max_ost}'. File system is '{self.file_system}' and has only {ost_count} OSTs.")
            #raise Exception(f"Invalid max_ost: '{self.max_ost}'. File system is '{self.file_system}' and has only {ost_count} OSTs.")

        # check if the max_volume is power of 2
        if self.max_volume > 0 and (self.max_volume & (self.max_volume - 1)) != 0:
            self.errors.append(f"Invalid max_volume: '{self.max_volume}'. max_volume must be a power of 2.")
        
    def load_execution(self):        
        self.mode = self.__get("execution", "mode").lower()
        self.job_manager = self.__get("execution", "job_manager").lower()
        modules_str = self.__get("execution", "modules")
        self.workdir = Path(self.__get("execution", "workdir"))

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
    
    def __str__(self):
        lines = []
        lines.append("IOPS Configuration:")
        
        # Nodes section
        lines.append(f"  \t\tNodes: {self.nodes}")
        lines.append(f"  \t\tMax Nodes: {self.max_nodes}")
        lines.append(f"  \t\tMax Processes Per Node: {self.max_processes_per_node}")
        
        # Storage section
        lines.append(f"  \t\tStorage Path: {self.path}")
        lines.append(f"  \t\tMax OST: {self.max_ost}")
        lines.append(f"  \t\tDefault Stripe Count: {self.default_stripe_count}")
        lines.append(f"  \t\tDefault Stripe Size: {self.default_stripe_size} bytes")
        lines.append(f"  \t\tFile System: {self.file_system}")

        # Execution section
        lines.append(f"  \t\tExecution Mode: {self.mode}")

        return "\n".join(lines)


