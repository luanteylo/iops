from enum import Enum

class TestType(Enum):
    """
    Tags for tests
    """
    FILESIZE = "filesize"
    COMPUTING = "computing"
    STRIPING = "striping"