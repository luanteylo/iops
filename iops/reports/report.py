from iops.core.config import IOPSConfig
from iops.core.runner import Round
from iops.util.tags import TestType

from pathlib import Path

from iops.util.generator import Generator

from datetime import datetime



class Report():


    def __init__(self, config : IOPSConfig, report_id : int, description : str):
        self.config = config
        self.report_id = report_id
        self.description = description

        self.reportdir = self.config.reportdir / f"report_{self.report_id}"
        self.reportdir.mkdir(parents=True, exist_ok=True)

        self.report_file = self.reportdir / "report.html"   

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

    def generate_report(self):    

        report_dict = {
            'current_date': datetime.now(),
            'reports_info': []
        }
        
        for round in self.rounds.values():
            # Firstly, we copy the files to the report folder
            round.graph_file.rename(self.reportdir / round.graph_file.name)
            round.csv_file.rename(self.reportdir / round.csv_file.name)

            # update the report_dict
            report_dict['reports_info'].append({                
                'test_title': self.__human_readable_title(round.test_type),
                'round_id': round.round_id,
                'graph_path': round.graph_file.name,
                'graph_title': self.__human_readable_title(round.test_type),
                'io_pattern': round.pattern.name,
                'file_mode': round.file_mode.name,
                'df':   round.best_df                
            })

        Generator.from_template(template_path=self.config.report_template, 
                    output_path=self.report_file,
                    info=report_dict)

        


                


