from iops.core.config import IOPSConfig
from iops.core.runner import Round
from iops.util.tags import TestType

from pathlib import Path

from iops.util.generator import Generator

from datetime import datetime

from rich.console import Console

console = Console()

class Report():


    def __init__(self, config : IOPSConfig, report_id : int, description : str):
        self.config = config
        self.report_id = report_id
        self.description = description

        self.report_file = self.config.workdir / "report.html"   
        self.txt_file = self.config.workdir / "iops.txt"

        self.rounds : dict[int, Round] = {}
        

    def add_round(self, round: Round):
        # testpath : Path, test_id : str, type : TestType, testdescription : str = ""
        if round.round_id in self.rounds:            
            raise ValueError(f"Round {round.round_id} already exists in report {self.report_id}!")
                
        self.rounds[round.round_id] = round

    def __human_readable_title(self, test_type: TestType):
        if test_type == TestType.FILESIZE:
            return "Varying the File Size"
        elif test_type == TestType.COMPUTING:
            return "Varying the Number of Computing Nodes"
        elif test_type == TestType.STRIPING:
            return "Varying the Striping Configuration"

    def generate_html(self):    

        report_dict = {
            'current_date': datetime.now(),
            'reports_info': []
        }
        
        for round in self.rounds.values():
            # Firstly, we copy the files to the report folder
            round.graph_file.rename(self.config.workdir / round.graph_file.name)
            round.csv_file.rename(self.config.workdir / round.csv_file.name)

            # update the report_dict
            report_dict['reports_info'].append({                
                'description': self.__human_readable_title(round.test_type),                
                'round': round                     
            })

        Generator.from_template(template_path=self.config.report_template, 
                    output_path=self.report_file,
                    info=report_dict)

        console.print(f"[bold green]Report {self.report_id} generated successfully.")
        console.print(f"[bold green]Report file: {self.report_file}")

        

    def generate_txt(self, run_time = None):
         # write a file summarizing the execution of the tests
        with open(self.txt_file, 'w') as f:
            f.write(f"Execution completed successfully in {run_time}\n")
            # print test setup
            f.write(f"Test setup:\n")
            f.write(f"\tMode: {self.config.mode}\n")
            f.write(f"\tSearch method: {self.config.search_method}\n")
            f.write(f"\tJob manager: {self.config.job_manager}\n")
            f.write(f"\tBenchmark: {self.config.benchmark_tool}\n")
            f.write(f"\tModules: {self.config.modules}\n")
            f.write(f"\tWorkdir: {self.config.workdir}\n")
            f.write(f"\tRepetitions: {self.config.repetitions}\n")
            f.write(f"\tTests: {self.config.tests}\n")       

            for round in self.rounds.values():
                f.write(f"\tRound {round.round_id} -  {round.test_type.name}:{round.pattern.name}:{round.file_mode.name} - Best parameter: {round.best_parameter} Best Bandwidth: {round.best_bw}\n")
                f.write("\n")
                for test in round.all_tests:
                    f.write(f"\t\tTest {test} - Bandwidth: {test.bw}\n")
                


