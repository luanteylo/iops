import pandas as pd
from pathlib import Path
import subprocess
import sys 

from rich.console import Console

from iops.core.config import IOPSConfig
from iops.reports.graphs import Graph
from iops.util.tags import TestType

from iops.core.runner import Round




console = Console()

class Report():
    def __init__(self, config : IOPSConfig, report_id : int, description : str):
        self.config = config
        self.report_id = report_id
        self.description = description

        self.reportdir = self.config.reportdir / f"report_{self.report_id}"
        self.reportdir.mkdir(parents=True, exist_ok=True)

        self.tests : dict = {}

    def __load_csv(self, csv_file : Path) -> pd.DataFrame:
        df = pd.read_csv(csv_file)
        return df
    
    def __generate_csv(self, input_path: Path, output_file: Path):
        args = [self.config.ior_2_csv, input_path, output_file]
        try:
            result = subprocess.run(args, check=True)
            if result.returncode == 0:
                console.print(f"[bold green] Generated {output_file}")
            else:
                console.print(f"[bold red]Error: Script {self.config.ior_2_csv} finished with a non-zero return code: {result.returncode}")
                sys.exit(1)
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error: Script execution failed: {e}")
            sys.exit(1)
    
    def add_test(self, test: Round):
        # testpath : Path, test_id : str, type : TestType, testdescription : str = ""
        if test.test_id in self.tests:            
            raise ValueError(f"Test ID {test.test_id} already exists!")
                
        self.tests[test.test_id] = {
            "testpath" : test.workdir,
            "testtype" : test.test_type,
            "testdescription": test.description,
            "csvfile" : None,          
            "df" : None,            
            "graphfile": None,
        }

    def build(self):
        for testid, test in self.tests.items():
            testtype = test["testtype"]
            testpath = test["testpath"]
            # Create the file name
            csvfile = self.reportdir / f"{testtype.name}_{testid}.csv"
            graphfile = self.reportdir / f"{testtype.name}_{testid}.svg"

            self.__generate_csv(testpath, csvfile)
            df = self.__load_csv(csvfile)

            if testtype == TestType.FILESIZE:
                Graph.filesize(df, graphfile)
            elif testtype == TestType.COMPUTING:
                Graph.computing(df, graphfile)
            elif testtype == TestType.STRIPING:
                Graph.striping(df, graphfile)
            
            # update the test dictionary
            test["csvfile"] = csvfile
            test["df"] = df
            test["graphfile"] = graphfile
    
    def summary(self) -> dict:        
        df_list = []
        graphs = []

        for test in self.tests.values():
            df_list.append(test["df"])            
            graphs.append({
                "filename" : test["graphfile"].relative_to(self.config.reportdir),
                "title" : test["testdescription"]
            })

        # Find the dataframe and column with the maximum bandwidth
        bw_col = "bw"
        max_df = max(df_list, key=lambda df: df[bw_col].max()) 
        # get the row with the max value in column bw
        row = max_df.loc[max_df[bw_col].idxmax()]        
        
        summary = {
            "info" : {
                "report_id": self.report_id,
                "max_bw": f"{row['bw']} MiB/s",
                "operation": row['access'],
                "num_nodes": row['nodes'],
                "num_tasks": row['tasks'],
                "clients_per_node": row['clients_per_node'],
                "file_size": f"{row['aggregate_filesize'] / 2**30} GB",
                "striping": row['path']
            },
            "graphs": graphs
        }
        return summary


            


