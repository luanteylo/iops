from iops.core.config import IOPSConfig
from iops.core.runner import Round




class Report():


    def __init__(self, config : IOPSConfig, report_id : int, description : str):
        self.config = config
        self.report_id = report_id
        self.description = description

        self.reportdir = self.config.reportdir / f"report_{self.report_id}"
        self.reportdir.mkdir(parents=True, exist_ok=True)

        self.rounds : dict[int, Round] = {}
        

    def add_round(self, round: Round):
        # testpath : Path, test_id : str, type : TestType, testdescription : str = ""
        if round.round_id in self.rounds:            
            raise ValueError(f"Round {round.round_id} already exists in report {self.report_id}!")
                
        self.rounds[round.round_id] = round


    
    def generate_report(self):
        for round in self.rounds.values():
            print(f"Generating report for round {round.round_id}")

        # def summary(self) -> dict:        
        #     df_list = []
        #     graphs = []

        #     for test in self.tests.values():
        #         df_list.append(test["df"])            
        #         graphs.append({
        #             "filename" : test["graphfile"].relative_to(self.config.reportdir),
        #             "title" : test["testdescription"]
        #         })

        #     # Find the dataframe and column with the maximum bandwidth
        #     bw_col = "bw"
        #     max_df = max(df_list, key=lambda df: df[bw_col].max()) 
        #     # get the row with the max value in column bw
        #     row = max_df.loc[max_df[bw_col].idxmax()]        
            
        #     summary = {
        #         "info" : {
        #             "report_id": self.report_id,
        #             "max_bw": f"{row['bw']} MiB/s",
        #             "operation": row['access'],
        #             "num_nodes": row['nodes'],
        #             "num_tasks": row['tasks'],
        #             "clients_per_node": row['clients_per_node'],
        #             "file_size": f"{row['aggregate_filesize'] / 2**30} GB",
        #             "striping": row['path']
        #         },
        #         "graphs": graphs
        #     }
        #     return summary


                


