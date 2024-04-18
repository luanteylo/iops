from iops.core.config import IOPSConfig
from iops.core.runner import Round

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


    
    def generate_report(self):

        report_dict = {
            'current_date': datetime.now()
        }

        for round in self.rounds.values():
            # update the report_dict with the round's information
            pass
            
        Generator.from_template(template_path=self.config.report_template, 
                                output_path=self.report_file,
                                info=report_dict)

        


                


