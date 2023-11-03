import subprocess
from pathlib import Path
import re
'''
This class contains methods to check the status of parallel file systems.
For now, only Lustre and BeeGFS are supported.
Local file system is also supported. In this case, the number of OSTs is 1.
'''

class FileSystems:
    def __init__(self, file_system: str, mount_point: str):
        self.file_system = file_system
        self.mount_point = mount_point

    def __get_ost_count_lustre(self) -> int:
        try:
            result = subprocess.check_output(["lfs", "df", self.mount_point])
            lines = result.decode('utf-8').split('\n')
            ost_count = sum('OST' in line for line in lines)
            return ost_count
        except Exception as e:
            raise Exception(f"An error occurred: {e}. Make sure Lustre is the right file system and the mount point is correct.")

    def __get_ost_count_beegfs(self) -> int:
        try:
            result = subprocess.check_output(["beegfs-ctl", "--getentryinfo", self.mount_point])
            output = result.decode('utf-8')

            # Use a regex to find the line with the number of storage targets
            match = re.search(r"Number of storage targets: desired: (\d+)", output)

            if match:
                # Extract the first group, which is the desired number of storage targets
                ost_count = int(match.group(1))
                return ost_count
            else:
                raise Exception("Could not find the number of storage targets in the output.")

        except Exception as e:
            raise Exception(f"An error occurred: {e}. Make sure BeeGFS is the right file system and the mount point is correct.")


    def get_ost_count(self) -> int:
        if self.file_system.lower() == 'lustre':
            return self.__get_ost_count_lustre()
        elif self.file_system.lower() == 'beegfs':
            return self.__get_ost_count_beegfs()
        elif self.file_system.lower() == 'local':
            return 1
        else:
            raise Exception(f"File system {self.file_system} is not supported.")


    def check_path(self, inner_folder=None) -> bool:        
        # Check if the path is valid.
        # If an inner folder is given as input, it will check from self.mount_point / inner_folder.
        full_path = Path(self.mount_point)
        if inner_folder:
            full_path = full_path / inner_folder

        return full_path.is_dir()

    
   
