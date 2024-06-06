
from iops.core.config import IOPSConfig
from iops.util.generator import Generator
from iops.util.tags import jobManager, TestType, Pattern, FileMode

from pathlib import Path
from abc import ABC, abstractmethod
import copy

from datetime import datetime
from abc import ABC, abstractmethod
import subprocess
import pandas as pd

class Test(ABC):
    """
    Represents a test to be executed in the IOPS benchmark. 
    This class serves as a base class for creating test scenarios with various configurations and behaviors. 
    It is designed to be subclassed, with subclasses needing to process specific test parameters and implement the method to build necessary files.
    """
    _id_counter = 0

    def __init__(self, config: 'IOPSConfig', round_path: Path, test_parameters: dict):
        """
        Initializes a new test instance, setting up essential file paths and storing configuration details.
        
        :param config: Configuration object containing settings for I/O operations.
        :param round_path: Base path where test files will be located.
        :param test_parameters: Dictionary of parameters that define test specifics. These parameters need to be handled appropriately by any class that inherits from this class.
        """
        type(self)._id_counter += 1
        self.test_id = self._id_counter        
        
        self.config = config
        self.round_path = round_path
        self.test_parameters = copy.deepcopy(test_parameters)

        self.batch_path = round_path / f"test_{self.test_id}"

        self.batch_file = self.batch_path / f"batch_{self.test_id}.sh"
        self.summary_file = self.batch_path / f"summary_test_{self.test_id}_$(date +%Y%m%d%H%M%S)_$RANDOM.out"
        self.csv_file = self.batch_path / f"result.csv"

        self.df = None
    
    @property
    def bw(self):
        if self.df is not None:
            return self.df["bw"].mean()
        else:
            return None
    
    @property
    def volume(self) -> int:
        """
        The volume of data involved in the test, in MB.
        """
        return self.test_parameters[TestType.FILESIZE]
    
    @property
    def folder_index(self) -> int:
        """
        The index of the directory within the storage hierarchy where the test files will be placed.
        """
        return self.test_parameters[TestType.STRIPING]
    
    @property
    def computing(self) -> int:
        """
        The number of computing nodes or processes dedicated to this test.
        """
        return self.test_parameters[TestType.COMPUTING]

    @classmethod
    def create_test(cls, pattern: Pattern, file_mode: FileMode, config: 'IOPSConfig', round_path: Path, test_parameters: dict) -> 'Test':
        """
        Factory method to create test instances based on the test pattern and operation.
        
        :param pattern: The I/O pattern for the test.
        :param operation: The type of operation to be performed.
        :param config: Configuration object for the test.
        :param round_path: Path where test files will be located.
        :param test_parameters: Dictionary of specific test parameters.
        :return: An instance of a subclass of Test.
        """
        if pattern == Pattern.SEQUENTIAL and file_mode == FileMode.SHARED:
            return TestIORSeq(config, round_path, test_parameters)
        elif pattern == Pattern.RANDOM and file_mode == FileMode.SHARED:
            return TestIORRandom(config, round_path, test_parameters) 
        # Add more elif statements for other test types as needed
        else:
            raise ValueError(f"Unsupported test pattern and file mode combination: {pattern}:{file_mode}")

    @abstractmethod
    def build_files(self) -> None:
        """
        Abstract method that must be implemented by subclasses to generate the files needed to execute the test.
        Subclasses should provide their own implementation to handle file generation based on the test configuration and parameters.
        """
        pass

    def template(self):
        if self.config.job_manager == jobManager.SLURM:
            return self.config.slurm_template   
        elif self.config.job_manager == jobManager.LOCAL:
            return self.config.local_template
        else:
            return None     
    
    def load_results(self):
        """
        Load the results of the tests
        """
        args = [self.config.ior_2_csv, self.batch_path, self.csv_file]
        result = subprocess.run(args, capture_output=True)
        if result.returncode != 0:
            raise ValueError(f"Error converting IOR output to CSV: {result.stderr}")
        
        self.df = pd.read_csv(self.csv_file)
        

    @classmethod
    def from_existing(cls, existing_test: 'Test'):
        """
        Creates a new instance based on an existing test instance. This method dynamically determines the class of the existing test and creates a new instance of that class.

        :param existing_test: An instance of a subclass of Test from which to create a new instance.
        """
        if isinstance(existing_test, Test):
            # Dynamically get the class of the existing test and use it to create a new instance.
            existing_class = type(existing_test)
            return existing_class(config=existing_test.config, 
                                  round_path=existing_test.round_path, 
                                  test_parameters=existing_test.test_parameters)
        else:
            raise TypeError(f"Cannot create a new instance from the given test object. It must be a non-abstract subclass of Test.")

    def __repr__(self):
        msg_str = f"\t{self.test_id:04}: "
        for key, value in self.test_parameters.items():            
            msg_str += f"\[{key.name}={value}] "
        
        return msg_str

    def __eq__(self, other: 'Test') -> bool:
        return abs(self.bw - other.bw) <= self.config.static_bw_alpha    

    def __le__(self, other: 'Test') -> bool:
        return  self.bw < other.bw or self.__eq__(other)     
    
    def __ge__(self, other: 'Test') -> bool:
        return  self.bw > other.bw or self.__eq__(other)
    
    def __lt__(self, other: 'Test') -> bool:
        return  self.bw < other.bw and not self.__eq__(other)
    
    def __gt__(self, other: 'Test') -> bool:
        return  self.bw > other.bw and not self.__eq__(other)
    

        

class TestIORSeq(Test):
    """
    I/O pattern: sequential write in a single shared file.
    Parameters:
    - volume: The amount of data (in MB) involved in the test.
    - folder_index: The index of the directory where the test files will be placed (each directory represents a different striping setup)
    - computing: The number of computing nodes involved in the I/O operation.
    """

    def __init__(self, config: 'IOPSConfig', round_path: Path, test_parameters: dict):
        # Initialize base class with shared configurations and the round path
        super().__init__(config, round_path, test_parameters)
        
    
    def __get_ior_command(self, delete_generate_file: bool) -> str:
        """
        Generate the IOR command based on the parameters defined in TestIOR.
        """
        
        ior_command : str = "ior"

        block_size : int = self.volume / (self.config.processes_per_node * self.computing)
       
        # Add parameters to the command

        ior_command += f" -w" # only write operation for now
        ior_command += f" -t 1m"  
        ior_command += f" -b {int(block_size)}m"  

        # delete the generate file at the end
        if not delete_generate_file:
            ior_command += f" -k" 
        ior_command += f" -O summaryFile={self.summary_file}" # Path where the output will be written 
        ior_command += f" -O summaryFormat=default"
        # Path where the output will be written 
        ior_command += f" -o {self.config.get_stripe_folder(self.folder_index)}/test{self.test_id}.ior"
        
        return ior_command

    def build_files(self) -> None:
        """
        Generate a batch file capable of executing the IOR command generated by the previous method.
        """
        # First create the folder for the test
        self.batch_path.mkdir(parents=True, exist_ok=True)

        parameters = {}
        if self.config.modules is not None:
            parameters["modules"] = self.config.modules
    
        if self.config.slurm_constraint is not None:
            parameters["constraint"] = self.config.slurm_constraint
        
        if self.config.slurm_partition is not None:
            parameters["partition"] = self.config.slurm_partition
        
        if self.config.slurm_time is not None:
            parameters["time"] = self.config.slurm_time
        else:
            parameters["time"] = "04:00:00"
        
        parameters["job_name"] = f"iops_{self.test_id}"
        parameters["chdir"] = self.batch_file.parent
        parameters["ntasks"] = self.computing * self.config.processes_per_node
        parameters["nodes"] = self.computing
        parameters["ntasks_per_node"] = self.config.processes_per_node
        parameters["benchmark_cmd"] = self.__get_ior_command(True)
        
        # Generate the execution script
        Generator.from_template(template_path=self.template(), output_path=self.batch_file, info=parameters)
        


class TestIORRandom(Test):
    """
    I/O pattern: random write in a single shared file.
    Parameters:
    - volume: The amount of data (in MB) involved in the test.
    - folder_index: The index of the directory where the test files will be placed (each directory represents a different striping setup)
    - computing: The number of computing nodes involved in the I/O operation.
    """

    def __init__(self, config: 'IOPSConfig', round_path: Path, test_parameters: dict):
        # Initialize base class with shared configurations and the round path
        super().__init__(config, round_path, test_parameters)
        
    
    def __get_ior_command(self, delete_generate_file: bool) -> str:
        """
        Generate the IOR command based on the parameters defined in TestIOR.
        """
        
        ior_command : str = "ior"

        block_size : int = self.volume / (self.config.processes_per_node * self.computing)
       
        # Add parameters to the command

        ior_command += f" -w" # only write operation for now
        ior_command += f" -t 1m"  
        ior_command += f" -b {int(block_size)}m"  
        

        # delete the generate file at the end
        if not delete_generate_file:
            ior_command += f" -k"
        ior_command += f" -z" # random access
        ior_command += f" --random-offset-seed=1" # random seed
        ior_command += f" -O summaryFile={self.summary_file}" # Path where the output will be written 
        ior_command += f" -O summaryFormat=default"
        # Path where the output will be written 
        ior_command += f" -o {self.config.get_stripe_folder(self.folder_index)}/test{self.test_id}.ior"
        
        return ior_command

    def build_files(self) -> None:
        """
        Generate a batch file capable of executing the IOR command generated by the previous method.
        """
        # First create the folder for the test
        self.batch_path.mkdir(parents=True, exist_ok=True)

        parameters = {}
        if self.config.modules is not None:
            parameters["modules"] = self.config.modules
    
        if self.config.slurm_constraint is not None:
            parameters["constraint"] = self.config.slurm_constraint
        
        if self.config.slurm_partition is not None:
            parameters["partition"] = self.config.slurm_partition
        
        if self.config.slurm_time is not None:
            parameters["time"] = self.config.slurm_time
        else:
            parameters["time"] = "04:00:00"
        
        parameters["job_name"] = f"iops_{self.test_id}"
        parameters["chdir"] = self.batch_file.parent
        parameters["ntasks"] = self.computing * self.config.processes_per_node
        parameters["nodes"] = self.computing
        parameters["ntasks_per_node"] = self.config.processes_per_node
        parameters["benchmark_cmd"] = self.__get_ior_command(True)
        
        # Generate the execution script
        Generator.from_template(template_path=self.template(), output_path=self.batch_file, info=parameters)