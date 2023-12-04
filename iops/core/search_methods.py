from abc import ABC, abstractmethod

from pathlib import Path
from typing import Optional, List
from uuid import uuid4

from iops.util.tags import Operation, TestType, SearchType
from iops.core.config import IOPSConfig


class Test:
    test_id  : str = None
    test_type : TestType = None
    operation : Operation = None
    nodes : int = None
    processes_per_node : int = None    
    file_size : int = None
    storage_dir : Path = None
    workdir : Path = None
    description : str = None

    
    def __init__(self, other: Optional['Test'] = None, **kwargs):

        self.test_id = str(uuid4())

        if other is not None:                
            self.test_type = other.test_type
            self.operation = other.operation
            self.nodes = other.nodes
            self.processes_per_node = other.processes_per_node
            self.file_size = other.file_size
            self.storage_dir = other.storage_dir
            self.test_path = other.test_path
        else:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def __str__(self) -> str:
        return f"(Test ID: {self.test_id}, Test Type: {self.test_type}, Operation: {self.operation}, Nodes: {self.nodes}, Processes per node: {self.processes_per_node}, File size: {self.file_size}, Storage dir: {self.storage_dir}, Test path: {self.test_path}))"
   

        
class SearchMethod(ABC):
    
    def __init__(self, config : IOPSConfig):
        self.config = config                
    
    _registry = {}

    @classmethod
    def register(cls, name, subclass):
        cls._registry[name] = subclass

    @classmethod
    def create(cls, name, *args, **kwargs):
        if name not in cls._registry:
            raise ValueError(f"No search method registered under '{name}'")
        return cls._registry[name](*args, **kwargs)


    @abstractmethod
    def build_round(self, previous_round : Optional[List[Test]]=None, value: Optional[int]=None) -> List[Test]:
       raise NotImplementedError
    
    
class Greedy(SearchMethod):
    def __init__(self, config : IOPSConfig):
        super().__init__(config)

    '''
    The greedy search method is a simple search method that will uses IOR
    and execute the following steps:

    Round 1: deSearchMethodoutputodes
    - file size: the file size from round 1
    - fixed transfer size:  1MB
    - default striping configuration: benchmark_output path
    - search by the number of nodes from 1 to MAX_NODES (double each time)
    return the number of nodes that has the highest bandwidth

    Round 3: defining the striping configuration
    - file size: the file size from round 1
    - number of nodes: the number of nodes from round 2
    - fixed transfer size:  1MB
    - search by the striping configuration going though all output_stripe_folders
    return the striping configuration that has the highest bandwidth

    Round 4: defining the transfer size
    - file size: the file size from round 1
    - number of nodes: the number of nodes from round 2
    - striping configuration: the striping configuration from round 3
    - search by the transfer size from 1MB to MAX_TRANSFER_SIZE (double each time)
    return the transfer size that has the highest bandwidth
    '''

    def __file_size_round(self, start_size : int, end_size : int, base_test : Test) -> List[Test]:
        tests = []
        # Search by the file size from 256MB to MAX_VOLUME (double each time)
        # define workdir
        filesize_workdir = self.config.workdir / "filesize"
        file_size = start_size
        while file_size <= end_size:
            test = Test(base_test)
            test.file_size = file_size
            test.workdir = filesize_workdir / test.uuid
            tests.append(test)
            file_size *= 2            
        return tests
    
    def __compute_nodes_round(self, base_test : Test) -> List[Test]:
        tests = []
        # Search by the number of nodes from 1 to MAX_NODES (double each time)
        compute_nodes_workdir = self.config.workdir / "compute_nodes"

        nodes = 1
        while nodes <= self.config.max_nodes:
            test = Test(base_test)
            test.nodes = nodes
            test.workdir = compute_nodes_workdir / test.uuid
            tests.append(test)
            nodes *= 2            
        return tests
    
    def __striping_round(self, base_test : Test) -> List[Test]:
        tests = []
        # Search by the striping configuration going though all output_stripe_folders
        striping_workdir = self.config.workdir / "striping"
        for stripe_folder in self.config.stripe_folders:
            test = Test(base_test)
            test.storage_dir = self.config.filesystem_dir / stripe_folder
            test.workdir = striping_workdir / test.uuid
            tests.append(test)
        return tests

    def build_round(self, previous_round : Optional[List[Test]]=None, value: Optional[int]=None) -> List[Test]:
        if previous_round == None:
            # First round (File size)
            # Let's define the file size
            base_test = Test(            
                test_type = TestType.FILESIZE,
                operation = Operation.WRITE,
                nodes = min(self.config.max_nodes, 8),
                processes_per_node = self.config.processes_per_node,
                striping_path = self.config.filesystem_dir                
            )
            return  self.__file_size_round(start_size=256*2**20, # 256MB
                                            end_size=self.config.max_volume,                                           
                                            base_test=base_test)
        
        previous_test_type = previous_round[0].test_type

        match previous_test_type:
            case TestType.FILESIZE:
                                
                if value is None:
                    raise ValueError("The value parameter is required for the computing round")
                
                # Let's define the number of nodes
                base_test = Test(
                    test_type = TestType.COMPUTING,
                    operation = Operation.WRITE,
                    file_size = value,
                    processes_per_node = self.config.processes_per_node,
                    striping_path = self.config.filesystem_dir
                )
                return self.__compute_nodes_round(base_test=base_test)
            
            case TestType.COMPUTING:
                if value is None:
                    raise ValueError("The value parameter is required for the computing round")
                # Let's define the striping configuration
                base_test = Test(
                    test_type = TestType.STRIPING,
                    operation = Operation.WRITE,
                    file_size = previous_round[0].file_size,
                    nodes = value,
                    processes_per_node = self.config.processes_per_node,                  
                )
                return self.__striping_round(base_test=base_test)
            
            case TestType.STRIPING:
                return None

# Register the subclass
SearchMethod.register(SearchType.GREEDY, Greedy)
         


# # Test implementation
# config = IOPSConfig("/home/luan/Devel/io-ps/default_config.ini")        

# sm = SearchMethod.create(SearchType.GREEDY, config)

# def print_round(round : List[Test]):
#     for test in round:
#         print(test)

# rounds = sm.build_round()

# print("First round")
# print_round(rounds)
# print("Second round")
# rounds = sm.build_round(rounds, 256*2**20)
# print_round(rounds)
# print("Third round")
# rounds = sm.build_round(rounds, 32)
# print_round(rounds)
