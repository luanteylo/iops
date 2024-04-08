import configparser
import re
from rich.console import Console
from rich.traceback import install
from pathlib import Path

from iops.util.tags import jobManager, ExecutionMode, BenchmarkTool, SearchType


install(show_locals=True)

console = Console()



class IOPSConfig:
    def __init__(self, config_path: str):
        self.config = configparser.ConfigParser()
        self.config_path = config_path
        self.config.read(config_path)


        # Nodes configuration
        self.max_nodes = None
        self.processes_per_node = None

        # Storage configuration
        self.filesystem_dir = None
        self.max_volume = None
        self.stripe_folders = None       

        # Execution configuration
        self.mode = None
        self.search_method = None
        self.job_manager = None
        self.benchmark_tool = None
        self.modules = None
        self.workdir = None
        self.reportdir = None # not in the .ini file
        self.repetitions = None

        # Templates & scripts
        self.slurm_template = None
        self.report_template = None
        self.ior_2_csv = None

        # Slurm configuration
        self.slurm_constraint = None
        self.slurm_partition = None
        self.slurm_time = None

        self.errors = []
        
        self.load_nodes()
        self.load_storage()
        self.load_execution()
        self.load_templates()
        self.load_slurm()

        if self.errors:
            for error in self.errors:
                console.print("[bold red]Error:[/bold red] [white]{}[/white]".format(error))
            raise Exception("Configuration file is invalid. Please fix the errors above.")


    def __get(self, section, key):
        value = self.config.get(section, key)       
        if "#" in value:
            value = value.split("#")[0].strip()
        return value

    def __format_error(self, section, key, value, valid_values=None, custom_message=None):
        if custom_message:
            return f"Invalid value: '{value}' for '{key}' in section '{section}'. {custom_message}"
        return f"Invalid value: '{value}' for '{key}' in section '{section}'. Allowed values are '{', '.join(valid_values)}'.\nDid you remove the '|' character from the .ini file?"

    def load_nodes(self):
        self.max_nodes = int(self.__get("nodes", "max_nodes"))
        self.processes_per_node = int(self.__get("nodes", "processes_per_node"))
        
        if self.max_nodes <= 0:
            self.errors.append(self.__format_error(section="nodes", 
                                                   key="max_nodes", 
                                                   value=self.max_nodes,
                                                   custom_message="Number of nodes need to be greater than zero."))
            
        if self.processes_per_node <= 0:
            self.errors.append(self.__format_error(section="nodes", 
                                                   key="processes_per_node", 
                                                   value=self.processes_per_node,
                                                   custom_message="Number of processes per node need to be greater than zero."))


    def load_storage(self):
        self.filesystem_dir = Path(self.__get("storage", "filesystem_dir"))        
        self.max_volume = int(self.__get("storage", "max_volume"))
        stripe_folders_str =  self.__get("storage", "stripe_folders")
        
        if not self.filesystem_dir.is_dir():
            self.errors.append(self.__format_error(section="storage",
                                                   key="filesystem_dir",
                                                   value=self.filesystem_dir,
                                                   custom_message="Invalid path."))
            
        # check if the max_volume is power of 2
        if self.max_volume > 0 and (self.max_volume & (self.max_volume - 1)) != 0:
            self.errors.append(self.__format_error(section="storage",
                                                   key="max_volume",
                                                   value=self.max_volume,
                                                   custom_message="Must be greater than zero and a power of 2!"))            
        # check stripe_folders
        # Parse and load the modules
        if stripe_folders_str.lower() == 'none':
            self.stripe_folders = None
        else:
            self.stripe_folders = [Path(stripe.strip()) for stripe in stripe_folders_str.split(',')]
            # check if the stripe_folders are valid
            for folder in self.stripe_folders:
                full_path = self.filesystem_dir / folder
                if full_path.is_dir() == False:
                    self.errors.append(self.__format_error(section="storage",
                                                          key="stripe_folders",
                                                          value=full_path,
                                                          custom_message="Invalid path."))
            
        
    def load_execution(self):                
        self.mode = self.__get("execution", "mode").lower()
        self.search_method = self.__get("execution", "search_method").lower()
        job_manager_str = self.__get("execution", "job_manager").lower()
        benchmark_tool_str  =  self.__get("execution", "benchmark_tool").lower()        
        modules_str = self.__get("execution", "modules")
        self.workdir = Path(self.__get("execution", "workdir"))
        self.repetitions = int(self.__get("execution", "repetitions"))
                
        if self.mode.upper() not in ExecutionMode.__members__:
            self.errors.append(self.__format_error(section="execution",
                                                   key="mode",
                                                   value=self.mode,
                                                   valid_values=ExecutionMode.__members__.keys()))            
        
        if self.search_method.upper() not in SearchType.__members__:
            self.errors.append(self.__format_error(section="execution",
                                                   key="search_method",
                                                   value=self.search_method,
                                                   valid_values=SearchType.__members__.keys()))
        else:
            self.search_method = SearchType[self.search_method.upper()]


        if job_manager_str.upper() not in jobManager.__members__:
            self.errors.append(self.__format_error(section="execution",
                                                    key="job_manager",
                                                    value=job_manager_str,
                                                    valid_values=jobManager.__members__.keys()))
        else:
            self.job_manager = jobManager[job_manager_str.upper()]
            
        if benchmark_tool_str.upper() not in BenchmarkTool.__members__:
            self.errors.append(self.__format_error(section="execution",
                                                    key="benchmark_tool",
                                                    value=benchmark_tool_str,
                                                    valid_values=BenchmarkTool.__members__.keys()))
        else:
            self.benchmark_tool = BenchmarkTool[benchmark_tool_str.upper()]


        # Parse and load the modules
        if modules_str.lower() == 'none':
            self.modules = None
        else:
            self.modules = [module.strip() for module in modules_str.split(',')]        
       
        if not self.workdir.is_dir():
            self.errors.append(self.__format_error(section="execution",
                                                   key="workdir",
                                                   value=self.workdir,
                                                   custom_message="Invalid path."))
        
        self.reportdir = self.workdir / "report"
        self.reportdir.mkdir(parents=True, exist_ok=True)

        if self.repetitions <= 0:
            self.errors.append(self.__format_error(section="execution",
                                                   key="repetitions",
                                                   value=self.repetitions,
                                                   custom_message="Must be greater than zero."))

    def load_templates(self):
        slurm_template_str = self.__get("template", "slurm_template")
        self.report_template = Path(self.__get("template", "report_template"))        
        self.ior_2_csv = Path(self.__get("template", "ior_2_csv"))        

        # check template file
        if slurm_template_str.lower() == 'none':
            self.slurm_template = None
        else:
            self.slurm_template = Path(slurm_template_str)
            # check if file exist
            if not self.slurm_template.is_file():
                self.errors.append(self.__format_error(section="template",
                                                       key="slurm_template",
                                                       value=self.slurm_template,
                                                       custom_message="File not found."))
            
        if self.job_manager == jobManager.SLURM and self.slurm_template == None:
            self.errors.append(self.__format_error(section="template",
                                                   key="slurm_template",
                                                   value=self.slurm_template,
                                                   custom_message="When using slurm, a template file needs to be provided."))
        
        if not self.ior_2_csv.is_file():
            self.errors.append(self.__format_error(section="template",
                                                   key="ior_2_csv",
                                                   value=self.ior_2_csv,
                                                   custom_message="File not found."))
        
        if not self.report_template.is_file():
            self.errors.append(self.__format_error(section="template",
                                                   key="report_template",
                                                   value=self.report_template,
                                                   custom_message="File not found."))

    def load_slurm(self):
        slurm_constraint_str = self.__get("slurm", "slurm_constraint")
        slurm_partition_str = self.__get("slurm", "slurm_partition")
        slurm_time_str = self.__get("slurm", "slurm_time")

        # Parse the slurm_constraint
        if slurm_constraint_str.lower() == 'none':
            self.slurm_constraint = None
        else:
            self.slurm_constraint = [constraint.strip() for constraint in slurm_constraint_str.split(',')]
        
        if slurm_partition_str.lower() == 'none':
            self.slurm_partition = None
        else:
            self.slurm_partition = slurm_partition_str
        
        if slurm_time_str.lower() == 'none':
            self.slurm_time = None
        else:
            # check if the time is in the correct format DD-HH:MM:SS or HH:MM:SS or MM:SS or SS
            if not re.match(r'^((\d+)-)?((\d+):)?((\d+):)?(\d+)$', slurm_time_str):
                self.errors.append(self.__format_error(section="execution",
                                                       key="slurm_time",
                                                       value=slurm_time_str,
                                                       custom_message="Invalid time format."))
            else:
                self.slurm_time = slurm_time_str

    def __str__(self) -> str:
        # print the configuration parameters
        return f"[bold]Nodes[/bold] \n" \
        f"max_nodes = {self.max_nodes}\n" \
        f"processes_per_node = {self.processes_per_node}\n\n" \
        f"[bold]Storage[/bold] \n" \
        f"filesystem_dir = {self.filesystem_dir}\n" \
        f"max_volume = {self.max_volume}\n" \
        f"stripe_folders = {self.stripe_folders}\n\n" \
        f"[bold]Execution[/bold] \n" \
        f"mode = {self.mode}\n" \
        f"job_manager = {self.job_manager}\n" \
        f"benchmark_tool = {self.benchmark_tool}\n" \
        f"modules = {self.modules}\n" \
        f"workdir = {self.workdir}\n" \
        f"reportdir = {self.reportdir}\n" \
        f"repetitions = {self.repetitions}\n\n" \
        f"[bold]Templates[/bold] \n" \
        f"slurm_template = {self.slurm_template}\n" \
        f"report_template = {self.report_template}\n" \
        f"ior_2_csv = {self.ior_2_csv}\n\n" \
        f"[bold]Slurm[/bold] \n" \
        f"slurm_constraint = {self.slurm_constraint}\n" \
        f"slurm_partition = {self.slurm_partition}\n" \
        f"slurm_time = {self.slurm_time}\n"
        
