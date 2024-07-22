import configparser
import re
import os
from rich.console import Console
from rich.traceback import install
from pathlib import Path

from rich.progress import BarColumn, TextColumn
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt


from iops.util.tags import jobManager, ExecutionMode, BenchmarkTool, SearchType, TestType, Pattern, FileMode
from iops.util.tags import VolumeValidation
from typing import List, Tuple


install(show_locals=True)

console = Console()
                            
custom_columns = [
    TextColumn("[bold blue]{task.description}"),
    BarColumn(),
    TextColumn("{task.completed}/{task.total} ({task.percentage:.2f}%)"),
]


class IOPSConfig:
    def __init__(self, config_path: str):
        self.config = configparser.ConfigParser()
        self.config_path = config_path
        self.config.read(config_path)


        # Nodes configuration
        self.min_nodes = None
        self.max_nodes = None
        self.processes_per_node = None

        # Storage configuration
        self.filesystem_dir = None
        self.min_volume = None
        self.max_volume = None
        self.volume_step = None
        self.default_stripe = None
        self.stripe_folders = None
        self.stripe_counts = None      

        # Execution configuration
        self.mode = None
        self.search_method = None
        self.job_manager = None
        self.benchmark_tool = None
        self.modules = None
        self.workdir = None
        self.repetitions = None
        self.tests = None
        self.wait_range = None

        # Templates & scripts
        self.slurm_template = None
        self.report_template = None
        self.ior_2_csv = None

        # Slurm configuration
        self.slurm_constraint = None
        self.slurm_partition = None
        self.slurm_time = None

        # local the configuration (for now)
        self.local_template = None

        # environment variable to point the iops directory
        self.iops_home = None

        # static parameters
        self.static_bw_alpha = 10 # 10 mbps

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
    
    def __get_next_index(self):
        # Get the next index for the execution folder
        if self.workdir.is_dir() == False:
            return 0
        else:
            existing_folders = [folder for folder in self.workdir.iterdir() if folder.name.startswith('execution_')]
            if existing_folders:
                indexes = [int(folder.name.split('_')[1]) for folder in existing_folders]
                next_index = max(indexes) + 1
            else:
                next_index = 0
            return next_index

    def __build_io_patterns(self, patterns_str: List[str]) -> List[Tuple[Pattern, FileMode]]:
        io_patterns = []
        for pattern in patterns_str:                
            pattern = pattern.split(':')                        
            if len(pattern) != 2:
                raise ValueError(f"Invalid pattern: {pattern}. Expected format: 'pattern:file_mode'")
            pattern_type = pattern[0]
            file_mode = pattern[1]
            if pattern_type.upper() not in Pattern.__members__:
                raise ValueError(f"Invalid Pattern: {pattern_type}")
            if file_mode.upper() not in FileMode.__members__:
                raise ValueError(f"Invalid FileMode: {file_mode}")
            io_patterns.append((Pattern[pattern_type.upper()], FileMode[file_mode.upper()]))
        
        return io_patterns

    def __build_tests(self, tests_str: List[str]) -> List[TestType]:
        # Return the TestType based on the string
        tests = []        
        for test in tests_str:          
            if test.upper() not in TestType.__members__:                
                raise ValueError(f"Invalid TestType: {test}")
            else:
                tests.append(TestType[test.upper()])            
        return tests

    def __format_error(self, section, key, value, valid_values=None, custom_message=None):
        if custom_message:
            return f"Invalid value: '{value}' for '{key}' in section '{section}'. {custom_message}"
        return f"Invalid value: '{value}' for '{key}' in section '{section}'. Allowed values are '{', '.join(valid_values)}'"

    def load_nodes(self):
        self.min_nodes = int(self.__get("nodes", "min_nodes"))
        self.max_nodes = int(self.__get("nodes", "max_nodes"))
        self.processes_per_node = int(self.__get("nodes", "processes_per_node"))
        
        if self.max_nodes <= 0:
            self.errors.append(self.__format_error(section="nodes", 
                                                   key="max_nodes", 
                                                   value=self.max_nodes,
                                                   custom_message="Number of nodes need to be greater than zero."))
            
        if self.min_nodes <= 0:
            self.errors.append(self.__format_error(section="nodes", 
                                                   key="min_nodes", 
                                                   value=self.min_nodes,
                                                   custom_message="Number of nodes need to be greater than zero."))

        # check if the number of nodes is power of 2

        if (self.max_nodes & (self.max_nodes - 1)) != 0:
            self.errors.append(self.__format_error(section="nodes", 
                                                   key="max_nodes", 
                                                   value=self.max_nodes,
                                                   custom_message="Number of nodes need to be a power of 2."))
        
        if (self.min_nodes & (self.min_nodes - 1)) != 0:
            self.errors.append(self.__format_error(section="nodes", 
                                                   key="min_nodes", 
                                                   value=self.min_nodes,
                                                   custom_message="Number of nodes need to be a power of 2."))
            
        if self.processes_per_node <= 0:
            self.errors.append(self.__format_error(section="nodes", 
                                                   key="processes_per_node", 
                                                   value=self.processes_per_node,
                                                   custom_message="Number of processes per node need to be greater than zero."))

    def load_storage(self):
        self.filesystem_dir = Path(self.__get("storage", "filesystem_dir"))        
        self.min_volume = int(self.__get("storage", "min_volume"))
        self.max_volume = int(self.__get("storage", "max_volume"))
        self.volume_step = int(self.__get("storage", "volume_step"))
        self.default_stripe = int(self.__get("storage", "default_stripe"))
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
        # check if the min_volume is power of 2
        if self.min_volume > 0 and (self.min_volume & (self.min_volume - 1)) != 0:
            self.errors.append(self.__format_error(section="storage",
                                                   key="min_volume",
                                                   value=self.min_volume,
                                                   custom_message="Must be greater than zero and a power of 2!"))
            
        if self.min_volume >= self.max_volume:
            self.errors.append(self.__format_error(section="storage",
                                                   key="min_volume",
                                                   value=self.min_volume,
                                                   custom_message="Must be less than max_volume."))

        # check if the volume_step is power of 2
        if self.volume_step not in VolumeValidation.VALID_VOLUME_STEPS:
            self.errors.append(self.__format_error(section="storage",
                                                   key="volume_step",
                                                   value=self.volume_step,
                                                   custom_message=f"Must be one of the following values: {VolumeValidation.VALID_VOLUME_STEPS}."))

        # check stripe_folders
        if stripe_folders_str.lower() == 'none':
            self.stripe_folders = None
        else:
            self.stripe_folders = [folder.strip() for folder in stripe_folders_str.split(',')]
            # check if the default stripe is in the stripe folders
            if self.default_stripe not in range(len(self.stripe_folders)):
                self.errors.append(self.__format_error(section="storage",
                                                       key="default_stripe",
                                                       value=self.default_stripe,
                                                       custom_message="Invalid stripe folder index."))
            # check if the stripe folders are unique
            if len(self.stripe_folders) != len(set(self.stripe_folders)):
                self.errors.append(self.__format_error(section="storage",
                                                       key="stripe_folders",
                                                       value=self.stripe_folders,
                                                       custom_message="Stripe folders must be unique."))
            # check if the folders exist
            for folder in self.stripe_folders:
                if not (self.filesystem_dir / folder).is_dir():
                    self.errors.append(self.__format_error(section="storage",
                                                           key="stripe_folders",
                                                           value=self.stripe_folders,
                                                           custom_message="Folder not found."))
            
        
    def load_execution(self):                
        self.mode = self.__get("execution", "mode").lower()
        self.search_method = self.__get("execution", "search_method").lower()
        job_manager_str = self.__get("execution", "job_manager").lower()
        benchmark_tool_str  =  self.__get("execution", "benchmark_tool").lower()        
        modules_str = self.__get("execution", "modules")
        self.workdir = Path(self.__get("execution", "workdir"))
        self.repetitions = int(self.__get("execution", "repetitions"))
        self.tests = self.__get("execution", "tests")
        self.io_patterns = self.__get("execution", "io_patterns")
        wait_range_str = self.__get("execution", "wait_range")
        # check if the environment variable IOPS_HOME is set
        self.iops_home = os.getenv("IOPS_HOME")
        if self.iops_home is None:
            self.errors.append(self.__format_error(section="execution",
                                                   key="iops_home",
                                                   value=self.iops_home,
                                                   custom_message="Environment variable IOPS_HOME is not set."))
                
        if self.mode.upper() not in ExecutionMode.__members__:
            self.errors.append(self.__format_error(section="execution",
                                                   key="mode",
                                                   value=self.mode,
                                                   valid_values=ExecutionMode.__members__.keys()))
        else:
            self.mode = ExecutionMode[self.mode.upper()]            
        
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

        # if the self.tests is a empty string, we append a error message
        if self.tests == "":
            self.errors.append(self.__format_error(section="execution",
                                                   key="tests",
                                                   value=self.tests,
                                                   custom_message="Test configuration is required."))
        else:
            # split the tests string and remove the white spaces
            tests_str = [test.strip() for test in self.tests.split(',')]            
            # create a list of tuples with the test configuration
            try:
                
                self.tests = self.__build_tests(tests_str)                
            except ValueError as e:
                self.errors.append(self.__format_error(section="execution",
                                                       key="tests",
                                                       value=self.tests,
                                                       custom_message=str(e)))
        
        if self.io_patterns == "":
            self.errors.append(self.__format_error(section="execution",
                                                   key="io_patterns",
                                                   value=self.io_patterns,
                                                   custom_message="IO Patterns is required."))
        else:
            # split the io_patterns string and remove the white spaces
            io_patterns_str = [io_pattern.strip() for io_pattern in self.io_patterns.split(',')]           
            # create a list of tuples with the io patterns            
            try:
                self.io_patterns = self.__build_io_patterns(io_patterns_str)                
            except ValueError as e:
                self.errors.append(self.__format_error(section="execution",
                                                       key="io_patterns",
                                                       value=self.io_patterns,
                                                       custom_message=str(e)))
        
        # check if  the tests pattern is valid considering the execution mode
        if self.job_manager == jobManager.LOCAL:
            for test in self.tests:
                if test in [TestType.COMPUTING, TestType.STRIPING]:
                    self.errors.append(self.__format_error(section="execution",
                                                       key="tests",
                                                       value=f"{test.name}",
                                                       custom_message=f"Test Type {test.name} only filesize test is allowed when using {self.job_manager.name} job manager."))
        # Parse and load the modules
        if modules_str.lower() == 'none':
            self.modules = None
        else:
            self.modules = [module.strip() for module in modules_str.split(',')]        
  
      
        # if it is running in debug mode we may want to pointing to the folder given by the user
        # in this case we ask the user to confirm the folder
        create_folder = True
        if self.mode == ExecutionMode.DEBUG:
            create_folder = False            
            console.print(f"[bold yellow]Debug Mode Warning:[/bold yellow] the folder {self.workdir} will be used")
            if Prompt.ask("[bold cyan]Do you want to use this folder?[/bold cyan]", choices=["yes", "no"], default="yes") == "no":
                create_folder = True        
        
        if create_folder:
            self.workdir = self.workdir / f"execution_{self.__get_next_index()}"
        
        if self.repetitions <= 0:
            self.errors.append(self.__format_error(section="execution",
                                                   key="repetitions",
                                                   value=self.repetitions,
                                                   custom_message="Must be greater than zero."))
        # wait time between test execution 
        if wait_range_str.lower() == 'none':
            self.wait_range = None
        else:
            self.wait_range = [int(wait.strip()) for wait in wait_range_str.split(',')]
            # check the wait range
            if len(self.wait_range) != 2:
                self.errors.append(self.__format_error(section="execution",
                                                       key="wait_range",
                                                       value=self.wait_range,
                                                       custom_message="Invalid wait range."))

            if self.wait_range[0] < 0 or self.wait_range[1] < 0:
                self.errors.append(self.__format_error(section="execution",
                                                       key="wait_range",
                                                       value=self.wait_range,
                                                       custom_message="Wait range must be greater than zero."))
            
            if self.wait_range[0] > self.wait_range[1]:
                self.errors.append(self.__format_error(section="execution",
                                                       key="wait_range",
                                                       value=self.wait_range,
                                                       custom_message=f"Invalid wait range: {self.wait_range[0]} should be greater than {self.wait_range[1]}"))

        

    def load_templates(self):
        slurm_template_str = os.path.expandvars(self.__get("template", "slurm_template"))
        local_template_str = os.path.expandvars(self.__get("template", "local_template"))

        self.report_template = os.path.expandvars(self.__get("template", "report_template"))    
        self.report_template = Path(self.report_template)    
        self.ior_2_csv = Path(self.__get("template", "ior_2_csv"))        

        # check template file
        if slurm_template_str.lower() == 'none':
            self.slurm_template = None
        else:
            self.slurm_template = Path(slurm_template_str)
            # check if file exist
            if not self.slurm_template.is_file:
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
        
        # check local template file
        if local_template_str.lower() == 'none':
            self.local_template = None
        else:
            self.local_template = Path(local_template_str)
            # check if file exist
            if not self.local_template.is_file():
                self.errors.append(self.__format_error(section="template",
                                                       key="local_template",
                                                       value=self.local_template,
                                                       custom_message="File not found."))

        if self.job_manager == jobManager.LOCAL and self.local_template == None:
            self.errors.append(self.__format_error(section="template",
                                                   key="local_template",
                                                   value=self.local_template,
                                                   custom_message="When using local, a local template file needs to be provided."))


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

    def print_config( self, skip_confirmation: bool):
        # Display startup message with a panel
        console.print(Panel(f"[bold green]Starting test with configuration file {self.config_path}...", expand=False))
        
        # Create a table for node information   
        table = Table(show_header=True, header_style="bold blue", box=box.SIMPLE)        
        table.add_column("Setting", style="dim", width=30)
        table.add_column("Value")
        table.add_row("Min Nodes", str(self.min_nodes))
        table.add_row("Max Nodes", str(self.max_nodes))        
        table.add_row("Processes Per Node", str(self.processes_per_node))

        # Create a table for storage information
        table.add_row("")
        table.add_row("File System Dir:", str(self.filesystem_dir))      
        table.add_row("Min Volume", f"{self.min_volume}MB")          
        # print max volume in MB
        table.add_row("Max Volume", f"{self.max_volume}MB")
        table.add_row("Volume Step", f"{self.volume_step}MB")
        stripe_folders = self.stripe_folders
        if stripe_folders is not None:        
            stripe_folders = ", ".join(f"{stripe}" for stripe in self.stripe_folders)
        table.add_row("Stripe Folders", str(stripe_folders))


        # Create a table for execution information
        table.add_row("")    
        table.add_row("Mode", self.mode.name)    
        table.add_row("Search Method", self.search_method.name)
        table.add_row("Job Manager", self.job_manager.name)
        
        
        modules = self.modules
        if modules is not None:        
            modules = ", ".join(f"{module}" for module in self.modules)
        table.add_row("Modules", str(modules))        
        table.add_row("Workdir", str(self.workdir))
        table.add_row("Tests", ", ".join([f"{test.name}" for test in self.tests]  ))
        table.add_row("IO Patterns", ", ".join([f"{pattern[0].name}:{pattern[1].name}" for pattern in self.io_patterns]))
        table.add_row("Repetitions", str(self.repetitions))

        table.add_row("")  
        table.add_row("Slurm Template", str(self.slurm_template))
        table.add_row("Local Template", str(self.local_template))
        table.add_row("Report Template", str(self.report_template))
        table.add_row("ior_2_csv script", str(self.ior_2_csv))

        table.add_row("")
        slurm_constraint = self.slurm_constraint
        if slurm_constraint is not None:
            slurm_constraint = ", ".join(f"{constraint}" for constraint in self.slurm_constraint)
        table.add_row("Slurm Constraint", str(slurm_constraint))
        table.add_row("Slurm Partition", str(self.slurm_partition))
        table.add_row("Slurm Time", str(self.slurm_time))
        table.add_row("")

        table.add_row("")
        # Print the tables with section headers and horizontal rules   
        console.print(table)

        console.print("[bold yellow]Warning:[/bold yellow] You may need to adapt the template file for your system. Check the options in 'iops/templates/'\n")


        if not skip_confirmation:
            # Ask for user confirmation
            confirmed = Prompt.ask("[bold cyan]Is this setup correct?[/bold cyan]", choices=["yes", "no"], default="yes")
            
            if confirmed.lower() != "yes":
                console.print("[bold red]Aborting test due to incorrect setup.")
                exit(1)
        
        # the setup is correct create the folders
        # Create the workdir folder
        try:
            self.workdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            console.print(f"[bold red]Error creating the workdir folder: {self.workdir}")
            raise e
            
        #console.print(Panel(f"[bold green]Starting test...", expand=True))

    def get_stripe_folder(self, index: int) -> Path:
        # Return the stripe folder based on the index.
        # The function most return the full path to the folder considering the filesystem_dir
        if self.stripe_folders is None or index >= len(self.stripe_folders):
            return None
        return self.filesystem_dir / self.stripe_folders[index]
    
    @property
    def wait_start(self):
        if self.wait_range is None:
            return 0
        return self.wait_range[0]
    
    @property
    def wait_end(self):
        if self.wait_range is None:
            return 0
        return self.wait_range[1]

        