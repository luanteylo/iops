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


from iops.util.tags import jobManager_Tag, ExecutionMode, BenchmarkTool, SearchType, Parameter, Pattern, FileMode
from iops.util.tags import VolumeValidation, TestType
from iops.util.job_manager import JobManager
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
        self.cores_per_node = None

        # Storage configuration
        self.filesystem_dir = None
        self.min_volume = None
        self.max_volume = None
        self.volume_step = None
        self.default_stripe = None
        self.stripe_folders = None
        self.stripe_counts = None      

        # Execution configuration
        self.test_type = None
        self.mode = None
        self.search_method = None
        self.job_manager = None
        self.benchmark_tool = None
        self.modules = None
        self.workdir = None
        self.repetitions = None
        self.status_check_delay = 0
        self.tests = None
        self.wait_range = None
        self.walltime = None

        # Templates & scripts
        self.bash_template = None
        self.report_template = None
        self.ior_2_csv = None

        
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
        # Pattern: execution_<number>, e.g., execution_0, execution_123
        pattern = re.compile(r'^execution_(\d+)$')

        if not self.workdir.is_dir():
            return 0

        indexes = []
        for entry in self.workdir.iterdir():
            if entry.is_dir():
                match = pattern.match(entry.name)
                if match:
                    indexes.append(int(match.group(1)))

        return max(indexes, default=-1) + 1

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

    def __build_tests(self, tests_str: List[str]) -> List[Parameter]:
        # Return the TestType based on the string
        tests = []        
        for test in tests_str:          
            if test.upper() not in Parameter.__members__:                
                raise ValueError(f"Invalid TestType: {test}")
            else:
                tests.append(Parameter[test.upper()])            
        return tests

    def __format_error(self, section, key, value, valid_values=None, custom_message=None):
        if custom_message:
            return f"Invalid value: '{value}' for '{key}' in section '{section}'. {custom_message}"
        return f"Invalid value: '{value}' for '{key}' in section '{section}'. Allowed values are '{', '.join(valid_values)}'"

    def load_nodes(self):
        try:
            self.min_nodes = int(self.__get("nodes", "min_nodes"))
            self.max_nodes = int(self.__get("nodes", "max_nodes"))
            self.processes_per_node = int(self.__get("nodes", "processes_per_node"))
            self.cores_per_node = int(self.__get("nodes", "cores_per_node"))
        except ValueError as e:
            self.errors.append(self.__format_error(section="nodes",
                                                   key="min_nodes/max_nodes/processes_per_node/cores_per_node",
                                                   value="Value Error",
                                                   custom_message="All values must be integers."))
            return

        
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
      
        if self.cores_per_node <= 0:
            self.errors.append(self.__format_error(section="nodes", 
                                                   key="cores_per_node", 
                                                   value=self.cores_per_node,
                                                   custom_message="Number of cores per node need to be greater than zero."))

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
            if self.default_stripe >= len(self.stripe_folders) or self.default_stripe < 0:
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
        self.test_type = self.__get("execution", "test_type")
        self.mode = self.__get("execution", "mode").lower()
        self.search_method = self.__get("execution", "search_method").lower()
        job_manager_str = self.__get("execution", "job_manager").lower()
        benchmark_tool_str  =  self.__get("execution", "benchmark_tool").lower()        
        modules_str = self.__get("execution", "modules")
        self.workdir = Path(self.__get("execution", "workdir"))
        self.repetitions = int(self.__get("execution", "repetitions"))
        self.status_check_delay = int(self.__get("execution", "status_check_delay"))
        self.walltime = self.__get("execution", "wall_time")
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

        if self.test_type.upper() not in TestType.__members__:
            self.errors.append(self.__format_error(section="execution",
                                                   key="test_type",
                                                   value=self.test_type,
                                                   valid_values=TestType.__members__.keys()))
        else:
            self.test_type = TestType[self.test_type.upper()]

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


        if job_manager_str.upper() not in jobManager_Tag.__members__:
            self.errors.append(self.__format_error(section="execution",
                                                    key="job_manager",
                                                    value=job_manager_str,
                                                    valid_values=jobManager_Tag.__members__.keys()))
        else:
            # build the job manager
            
            self.job_manager = JobManager.factory(jobManager_Tag[job_manager_str.upper()])
            

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
        if self.job_manager == jobManager_Tag.LOCAL:
            for test in self.tests:
                if test in [Parameter.COMPUTING, Parameter.STRIPING]:
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
        # check if the status_check_delay is greater or equal than 0
        if self.status_check_delay < 0:
            self.errors.append(self.__format_error(section="execution",
                                                   key="status_check_delay",
                                                   value=self.status_check_delay,
                                                   custom_message="Must be greater than or equal to zero."))

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
        
        # check if the walltime is a valid time format
         # check if the time is in the correct format DD-HH:MM:SS or HH:MM:SS or MM:SS or SS
        if not re.match(r'^((\d+)-)?((\d+):)?((\d+):)?(\d+)$', self.walltime):
            self.errors.append(self.__format_error(section="execution",
                                                    key="wall_time",
                                                    value=self.walltime,
                                                    custom_message="Invalid time format."))
        

    def load_templates(self):
        bash_template_str = os.path.expandvars(self.__get("template", "bash_template"))
        self.report_template_str = os.path.expandvars(self.__get("template", "report_template"))    

        self.bash_template = Path(bash_template_str)
        self.report_template = Path(self.report_template_str)    
        self.ior_2_csv = Path(self.__get("template", "ior_2_csv"))        


        # check if the bash template file exist
        if not self.bash_template.is_file():
            self.errors.append(self.__format_error(section="template",
                                                   key="bash_template",
                                                   value=self.bash_template,
                                                   custom_message="File not found."))
        # check if the report template file exist
        if not self.report_template.is_file():
            self.errors.append(self.__format_error(section="template",
                                                   key="report_template",
                                                   value=self.report_template,
                                                   custom_message="File not found."))
        # check if the ior_2_csv file exist
        if not self.ior_2_csv.is_file():
            self.errors.append(self.__format_error(section="template",
                                                   key="ior_2_csv",
                                                   value=self.ior_2_csv,
                                                   custom_message="File not found."))

   

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
        table.add_row("Cores Per Node", str(self.cores_per_node))


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
        table.add_row("Default Stripe", self.stripe_folders[self.default_stripe])


        # Create a table for execution information
        table.add_row("")    
        table.add_row("Test Type", self.test_type.name)
        table.add_row("Mode", self.mode.name)    
        table.add_row("Search Method", self.search_method.name)
        table.add_row("Job Manager", str(self.job_manager))             
        table.add_row("Workdir", str(self.workdir))
        table.add_row("Tests", ", ".join([f"{test.name}" for test in self.tests]  ))
        table.add_row("IO Patterns", ", ".join([f"{pattern[0].name}:{pattern[1].name}" for pattern in self.io_patterns]))
        table.add_row("Repetitions", str(self.repetitions))
        table.add_row("Wait Range", str(self.wait_range))
        table.add_row("Status Check Delay", str(self.status_check_delay))
        table.add_row("Walltime", str(self.walltime))

        table.add_row("")  
        table.add_row("Script Template", str(self.bash_template))
        table.add_row("Report Template", str(self.report_template))
        table.add_row("ior_2_csv script", str(self.ior_2_csv))
     
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

        