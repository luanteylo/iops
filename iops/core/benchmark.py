from abc import ABC

from iops.util.tags import Operation
from typing import Optional, Tuple


class Benchmark(ABC):
    '''
    Abstract class for benchmarks.

    This class is used to build a command line for a benchmark.
    
    '''

    def __init__(self):
        self.parameters = {}
        self.command = ""

    def add_parameter(self, key: str, value: str):
        self.parameters[key] = value

    def get_command(self) -> str:
        command = self.command
        for param, value in self.parameters.items():
            command += f" {param} {value}"
        return command
    
    def __str__(self) -> str:
        return self.get_command()


class IOR(Benchmark):

    def __init__(self, operation: Optional[Operation] = None, transfer_size: Optional[int] = None, 
                 block_size: Optional[Tuple[int, str]] = None, keep_files: Optional[bool] = None, 
                 output_file: Optional[str] = None):
        super().__init__()

        self.command = "ior"
        
        if operation is not None:
            self.process_operation(operation)
        if transfer_size is not None:
            self.add_parameter("-t", str(transfer_size))
        if block_size is not None:
            self.process_block_size(*block_size)
        if keep_files is not None:
            self.add_parameter("-k", "" if keep_files else None)
        if output_file is not None:
            self.add_parameter("-o", output_file)

    def process_operation(self, operation):
        if operation == Operation.WRITE:
            self.add_parameter("-w", "")
        elif operation == Operation.READ:
            self.add_parameter("-r", "")

    def process_block_size(self, block_size, unit):
        self.add_parameter("-b", f"{block_size}{unit}")


    

   


#ior -w -t 1m -b 536870912.0b -k -o ${IOR_PATH}/testFile1.ior


# Usage
#ior = IOR(operation=Operation.WRITE, transfer_size=1, block_size=(512, "mb"), keep_files=True, output_file="testFile1.ior")
