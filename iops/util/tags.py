from enum import Enum

class TestType(Enum):
    """
    Tags for tests
    """    
    FILESIZE = "filesize"
    COMPUTING = "computing"
    STRIPING = "striping"

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

class jobManager(Enum):
    """
    Tags for job managers
    """
    SLURM = "slurm"
    LOCAL = "local"

class ExecutionMode(Enum):
    """
    Tags for execution modes
    """
    NORMAL = "normal"
    DEBUG = "debug"
    STAGGERED = "staggered"

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