"""
Allow running iops as a module: python -m iops
"""

import sys

from iops.main import main

if __name__ == "__main__":
    # Propagate main()'s return code, as the `iops` console script does.
    # Studio runs IOPS as `python -m iops`, so without this every command
    # (a failed `iops check` included) exited with status 0.
    sys.exit(main())
