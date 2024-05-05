from enum import Enum

class TestType(Enum):
    """
    Tags for tests
    """
    IOR_COM_SEQ_ONE = 1
    IOR_COM_SEQ_SHARED = 2
    IOR_COM_RANDOM_ONE = 3
    IOR_COM_RANDOM_SHARED = 4
    IOR_FILESIZE_SEQ_ONE = 5
    IOR_FILESIZE_SEQ_SHARED = 6

    IOR_STRIPING_SEQ_ONE = 7
    IOR_STRIPING_SEQ_SHARED = 8
    
    FILESIZE = "filesize"
    COMPUTING = "computing"
    STRIPING = "striping"

class Pattern(Enum):
    """
    Tags for I/O patterns
    """
    SEQUENTIAL = "sequential"
    RANDOM = "random"

class Operation(Enum):
    """
    Tags for operations
    """
    WRITE = "write"
    READ = "read"

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
    FAST = "fast"
    COMPLETE = "complete"
    DEBUG = "debug"

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