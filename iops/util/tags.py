from enum import Enum

class Parameter(Enum):
    """
    Tags for the parameter types
    """    
    FILESIZE = "filesize"
    COMPUTING = "computing"
    STRIPING = "striping"

class TestFlags(Enum):
    """
    Tags for test flags
    """
    KEEP_FILES = "keep_files"

class TestType(Enum):
    """
    Tags for test types
    """
    WRITE_ONLY = "write-only"
    WRITE_READ = "write-read"



class Pattern(Enum):
    """
    Tags for I/O patterns
    """
    SEQUENTIAL = "sequential"
    RANDOM = "random"


class FileMode(Enum):
    """
    Tags for file modes
    """
    SHARED = "shared"

class jobManager_Tag(Enum):
    """
    Tags for job managers
    """
    SLURM = "slurm"
    MSUB = "msub"
    LOCAL = "local"

class ExecutionMode(Enum):
    """
    Tags for execution modes
    """
    NORMAL = "normal"
    DEBUG = "debug"

class Operation(Enum):
    """
    Tags for I/O operations
    """
    WRITE = "write"    
    READ = "read"
   

class BenchmarkTool(Enum):
    """
    Tags for benchmark tools
    """
    IOR = "ior"

class SearchType(Enum):
    """
    Tags for search methods
    """
    GREEDY = "greedy"
    SMART = "smart"
    BINARY = "binary"

class VolumeValidation:
    # 256MB to 1GB
    VALID_VOLUME_STEPS = [2**i for i in range(8, 11)] 

