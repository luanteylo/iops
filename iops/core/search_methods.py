from abc import ABC, abstractmethod

from pathlib import Path
from typing import Optional, List

from rich.console import Console

from iops.util.tags import Operation
from iops.core.config import IOPSConfig


console = Console()

class Test:
    operation : Operation = None
    nodes : int = None
    processes_per_node : int = None    
    file_size : int = None
    striping_path : Path = None

    def __init__(self, other: Optional['Test'] = None):
        if other is not None:
            self.operation = other.operation
            self.nodes = other.nodes
            self.processes_per_node = other.processes_per_node
            self.file_size = other.file_size
            self.striping_path = other.striping_path


    

        
class SearchMethod(ABC):
    
    def __init__(self, config : IOPSConfig):
        self.config = config                
        

    @abstractmethod
    def build_round(self, previous_round : Optional[List[Test]]=None) -> List[Test]:
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
        file_size = start_size
        while file_size <= end_size:
            test = Test(base_test)
            test.file_size = file_size
            tests.append(test)
            file_size *= 2            
        return tests

    def build_round(self, previous_round : Optional[List[Test]]=None) -> List[Test]:

        if previous_round == None:
            # First round
            # Let's define the file size
            base_test = Test(
                operation = Operation.WRITE,
                nodes = min(self.config.max_nodes, 8),
                processes_per_node = self.config.processes_per_node,
                striping_path = self.config.filesystem_dir
            )
            return  self.__file_size_round(start_size=256*2**20, # 256MB
                                            end_size=self.config.max_volume,                                           
                                            base_test=base_test)



SearchMethod


        
            
            
            


# Test implementation
#config = IOPSConfig("../../default_config.ini")        
#greedy = Greedy(config)
#greedy.run()
        

