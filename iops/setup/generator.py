import configparser
import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from typing import List
from datetime import datetime

from iops.setup.iops_config import IOPSConfig
from iops.reports.report import Report


class Generator:
    @staticmethod
    def ini_file(file_name):
        logging.info("Generating default configuration file...")
        config_nodes = configparser.ConfigParser()
        config_storage = configparser.ConfigParser()
        config_execution = configparser.ConfigParser()

        config_template = configparser.ConfigParser()
    
        config_nodes['nodes'] = {
            'max_nodes': '32 # Max number of nodes that can be allocated (to limit computing tests)',
            'processes_per_node': '8 # The number of processes that will be used per node. For now, this is a static parameter',            
        }


        
        config_storage['storage'] = {
            'benchmark_output': '/path/to/storage # The path to the directory where the benchmark tool will write/read from',            
            'file_system': 'lustre | beegfs | local # Select the file system',
            'max_volume':  '34359738368 # Max volume size in bytes (to limit the size of the benchmarked file)',
            'output_stripe_folders': "ost_1, ost_2, ost_4, ost_8 # A list of folders with distinct striping setups.\n" \
            "# If 'None' is provided, the striping test will not be executed.\n" \
            "# For now, these folders need to be created manually inside the benchmark_output folder using the file system\n"\
            "# utility to define the correct striping setup. These folders need to be defined using a sequential number\n"\
            "# (the larger the number, the more OSTs); a good approach is to use the number of OSTs as this number.\n"\
            "# Otherwise, you may encounter problems in the striping graph.\n"
        }


        config_execution['execution'] = {
            'mode': 'fast | complete # Select the mode of execution',
            'job_manager': 'slurm | None # Specify the job manager. If "None" is provided, the benchmark will be executed locally',
            'slurm_constraint': 'constraint_1, constraint_2 | None # Some clusters use the slurm constraint parameter (-c) to define the resources. If that is your case, set the list of constraints here, otherwise put None',
            'modules': 'mpi, some_other_module | None # Specify the list of modules to load using "module add <module>". If "None" is provided, no modules are loaded',
            'workdir': '/path/to/workdir # # Specify the working directory, i.e., where the script files will be written',
            'repetitions': '5 # The number of repetitions for each test',
            
        }

        config_template['template'] = {
            'slurm_template': 'iops/templates/slurm_template.sh.j2 | None # If using Slurm, define the template file to generate the bash scripts. Otherwise, None.',
            'report_template': 'iops/templates/report_template.html # Template for the report HTML page.',
            'ior_2_csv': 'tools/ior_2_csv.py # Path to the ior_2_csv.py script.',            
        }

        
        with open(file_name, 'w') as config_file:
            config_file.write("# This is a default configuration file for IOPS.\n")        
            config_file.write("# Edit it to suit your needs.\n\n")
            config_nodes.write(config_file)

            config_storage.write(config_file)

            config_file.write("# Execution mode\n")
            config_file.write("# - fast: Run the benchmark without any waiting time between the tests (less accurate)\n")
            config_file.write("# - complete: Run the benchmark with random waiting times between the executions (more accurate)\n")
            config_execution.write(config_file)
            
            config_file.write("# Template and scripts \n")
            config_template.write(config_file)

        
        logging.info(f"Default configuration file generated as {file_name}")
    
    @staticmethod
    def slurm_script(template_path: Path, output_path: str, file_name: str, case: dict) -> None:
        '''
        Generates a bash script for a given case.
        The bash script is generated using the template file in template_path and is saved in the output_path directory.
        '''
        # create the Jinja2 environment and load the template
        env = Environment(loader=FileSystemLoader(str(template_path.parent)))
        template = env.get_template(template_path.name)

        # generate the script
        bash_script = template.render(**case)
        # write the script to a file
        script_filename = Path(output_path, file_name)
        with open(script_filename, 'w') as f:
            f.write(bash_script)

    @staticmethod
    def report(reports: List[Report], report_html : Path, config : IOPSConfig):        
        # Generate graphs
        reports_info = []

        for report in reports:
            report.build()      
            reports_info.append(report.summary())

        # create the Jinja2 environment and load the template
        env = Environment(loader=FileSystemLoader(str(config.report_template.parent)))
        template = env.get_template(config.report_template.name)

        with open(report_html.as_posix(), "w") as f:
            f.write(template.render(reports_info=reports_info, 
                                    current_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
      
#config = IOPSConfig(config_path="../../config.ini")
#report = Report(config, 1, "Test report")

#import uuid
#from iops.setup.tags import TestType

#config = IOPSConfig(config_path="../../config.ini")

#report1 = Report(config, 1, "Test report 1")
#report2 = Report(config, 2, "Test report 2")


#report1.add_test(config.workdir / "computing_0", uuid.uuid4(), TestType.COMPUTING)
#report1.add_test(config.workdir / "filesize_0", uuid.uuid4(), TestType.FILESIZE)
#report1.add_test(config.workdir / "striping_0", uuid.uuid4(), TestType.STRIPING)

#report2.add_test(config.workdir / "computing_1", uuid.uuid4(), TestType.COMPUTING)
#report2.add_test(config.workdir / "filesize_1", uuid.uuid4(), TestType.FILESIZE)

#Generator.report([report1, report2],  config.reportdir / "report.html", config)



