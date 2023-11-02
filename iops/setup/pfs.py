import subprocess
from pathlib import Path
'''
This class contains methods to check the status of parallel file systems.
For now, only Lustre and BeeGFS are supported.
Local file system is also supported. In this case, the number of OSTs is 1.
'''

class FileSystems:
    def __init__(self, file_system: str, mount_point: str):
        self.file_system = file_system
        self.mount_point = mount_point

    def __get_ost_count_lustre() -> int:
        try:
            result = subprocess.check_output(["lfs", "df", self.mount_point])
            lines = result.decode('utf-8').split('\n')
            ost_count = sum('OST' in line for line in lines)
            return ost_count
        except Exception as e:
            raise Exception(f"An error occurred: {e}. Make sure Lustre is the right file system and the mount point is correct.")

    def __get_ost_count_beegfs() -> int:
        try:
            result = subprocess.check_output(["beegfs-ctl", "--getentryinfo", self.mount_point])
            lines = result.decode('utf-8').split('\n')
            ost_count = sum('Storage targets:' in line for line in lines)
            return ost_count
        except Exception as e:
            raise Exception(f"An error occurred: {e}. Make sure BeeGFS is the right file system and the mount point is correct.")
    
    def get_ost_count(self) -> int:
        if self.file_system.lower() == 'lustre':
            return get_ost_count_lustre()
        elif self.file_system.lower() == 'beegfs':
            return get_ost_count_beegfs()
        elif self.file_system.lower() == 'local':
            return 1
        else:
            raise Exception(f"File system {self.file_system} is not supported.")


    def __check_path(self) -> bool:
        # check if path is valid
        return Path(self.mount_point).is_dir()
    
    def check_mount_point(self) -> bool:
        # first, we check if path is valid
        if not self.__check_path():
            return False
        # check if path is a mount point
        # we do not check if the path is a mount point for local file system
        if self.file_system.lower() == 'local' or Path(self.mount_point).is_mount():
            return True
