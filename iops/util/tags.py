from enum import Enum

class TestType(Enum):
    """
    Tags for tests
    """
    FILESIZE = "filesize"
    COMPUTING = "computing"
    STRIPING = "striping"


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
    