from iops.core.config import IOPSConfig
from iops.core.runner import Round

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

    
    def generate_report(self):

        report_dict = {
            'current_date': datetime.now(),
            'reports_info': []
        }

        for round in self.rounds.values():
            # update the report_dict
            report_dict['reports_info'].append({
                'report_id': round.round_id,
                'round_description': self.description,
                'max_bw': f"{round.df.bw.max()}MiB/s",
                'graph_path': round.graph_file,
                'graph_title': f"Round {round.test_type.name.lower()}",
                'operation': 'write',
                'num_tasks':round.df.loc[round.df['bw'].idxmax(), 'tasks'],
                'clients_per_node': round.df.loc[round.df['bw'].idxmax(), 'clients_per_node'],
                'num_nodes': round.df.loc[round.df['bw'].idxmax(), 'nodes'],
                'file_size': f"{(round.df.loc[round.df['bw'].idxmax(), 'aggregate_filesize'])/1024/1024}MiB",
                'striping': Path(round.df.loc[round.df['bw'].idxmax(), 'path']).parent,
            })

        Generator.from_template(template_path=self.config.report_template, 
                    output_path=self.report_file,
                    info=report_dict)

        


                


