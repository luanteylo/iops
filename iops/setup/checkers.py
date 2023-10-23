import logging
import subprocess


class Checker:

    @staticmethod
    def check_ior_installation() -> bool:
        '''
        Check if IOR is installed and available in $PATH.
        '''
        try:
            # Check if 'ior' binary is available
            subprocess.run(["ior", "-h"], check=True,stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logging.info("Ready to Go!")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Error: {e}")
            logging.warning(f"If you are able to run 'ior -h' from the command line, it may actually be working.")
            logging.warning(f"Versions more recent of IOR return a non-zero exit code when running \
                            'ior -h' with messing up the IOR installation check.")
        except FileNotFoundError:
            logging.error("Error: ior binary not found. Make sure it is installed and available in $PATH.")
        
        return False
    
