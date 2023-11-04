import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from matplotlib.ticker import MaxNLocator
import subprocess
import re
from rich.console import Console

from iops.setup.iops_config import IOPSConfig

console = Console()

class BasicReport:

    def __init__(self, report_id: int, config : IOPSConfig, filesize_path : Path, computing_path : Path, striping_path : Path):
        self.config = config

        self.report_id = report_id

        self.filesize_path = filesize_path
        self.computing_path = computing_path
        self.striping_path = striping_path

        self.report_dir = self.config.workdir / 'report/'
        
        self.filesize_csv = self.report_dir / f"filesize_{self.report_id}.csv"
        self.computing_csv = self.report_dir / f"computing_{self.report_id}.csv"
        self.striping_csv = self.report_dir /  f"striping_{self.report_id}.csv"

        self.filesize_png = self.report_dir / f"filesize_{self.report_id}.png"
        self.computing_png = self.report_dir / f"computing_{self.report_id}.png"
        self.striping_png = self.report_dir /  f"striping_{self.report_id}.png"

        self.report_html = self.report_dir / f"report_{self.report_id}.html"

        self.filesize_df = None 
        self.computing_df = None 
        self.striping_df = None 

        self.__load_data()
    
    def __load_data(self):
        # First generate the CSV files
        self.__generate_csv(self.filesize_path, self.filesize_csv)
        self.__generate_csv(self.computing_path, self.computing_csv)
        self.__generate_csv(self.striping_path, self.striping_csv)

        # Load pandas
        self.filesize_df = pd.read_csv(self.filesize_csv)
        self.computing_df = pd.read_csv(self.computing_csv)
        self.striping_df = pd.read_csv(self.striping_csv)


    def plot_filesize_graph(self):
        plt.figure(figsize=(12, 8))  # Increased size for better visibility

        self.filesize_df['aggregate_filesize_mb'] = self.filesize_df['aggregate_filesize'] / 2**20        
        # Customized line plot
        sns.lineplot(x='aggregate_filesize_mb', y='bw', data=self.filesize_df,
                    linewidth=2.5, color='royalblue', marker='o',
                     markersize=8, linestyle='-', errorbar='sd')
        
        # Scatter plot to add individual points
        sns.scatterplot(x='aggregate_filesize_mb', y='bw', data=self.filesize_df,
                        color='royalblue', marker='x', s=50)  # Adjust the color and size as needed

        # Adding gridlines for better readability
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)

        # Title and labels
        plt.title("File Size Test", fontsize=18, fontweight='bold')  # Increased font size and made bold
        plt.xlabel('Aggregate File Size (MiB)', fontsize=14)  # Increased font size
        plt.ylabel('Bandwidth (MB/s)', fontsize=14)  # Increased font size

        # Customizing axes ticks
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)

        #plt.show()

        plt.savefig(self.filesize_png)
        plt.close()
    
    def plot_computing_graph(self):
        plt.figure(figsize=(12, 8))  # Increased size for better visibility
  
        # Customized line plot
        sns.lineplot(x='nodes', y='bw', data=self.computing_df,
                    linewidth=2.5, color='royalblue',
                     marker='o', markersize=8, linestyle='-', errorbar='sd')
        
        # Scatter plot to add individual points
        sns.scatterplot(x='nodes', y='bw', data=self.computing_df,
                        color='royalblue', marker='x', s=50)  # Adjust the color and size as needed

        # Adding gridlines for better readability
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)

        # Title and labels
        plt.title("Computing nodes Test", fontsize=18, fontweight='bold')  # Increased font size and made bold
        plt.xlabel('Number Computing Nodes', fontsize=14)  # Increased font size
        plt.ylabel('Bandwidth (MB/s)', fontsize=14)  # Increased font size

        # Customizing axes ticks
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)

        # Ensure x-axis uses only integer values
        plt.gca().xaxis.set_major_locator(MaxNLocator(integer=True))

        #plt.show()

        plt.savefig(self.computing_png)
        plt.close()
    
    def plot_striping_graph(self):
        plt.figure(figsize=(12, 8))  # Increased size for better visibility
        
        # Extracting folder names
        self.striping_df['striping'] = self.striping_df['path'].apply(lambda x: Path(x).parent.name)
        
        # Extracting the numeric portion from the folder names
        self.striping_df['order'] = self.striping_df['striping'].apply(lambda x: int(re.search(r'\d+', x).group()))
        
        # Sorting the DataFrame based on the numeric portion
        self.striping_df = self.striping_df.sort_values(by='order')
        
        # Customized line plot
        sns.lineplot(x='striping', y='bw', data=self.striping_df,
                     linewidth=2.5, color='royalblue', marker='o',
                      markersize=8, linestyle='-', errorbar='sd')
        
        # Scatter plot to add individual points
        sns.scatterplot(x='striping', y='bw', data=self.striping_df,
                        color='royalblue', marker='x', s=50)  # Adjust the color and size as needed

        # Adding gridlines for better readability
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)

        # Title and labels
        plt.title("Striping Test", fontsize=18, fontweight='bold')  # Increased font size and made bold
        plt.xlabel('Striping directory', fontsize=14)  # Increased font size
        plt.ylabel('Bandwidth (MB/s)', fontsize=14)  # Increased font size

        # Customizing axes ticks
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)

        #plt.show()
        plt.savefig(self.striping_png)
        plt.close()
    
    def __generate_csv(self, input_path : Path, output_path : Path):       
        # First generate CSV files using ior_2_csv tool                
        args = [self.config.ior_2_csv, input_path, output_path]         
        # Call the script and wait for it to finish
        try:
            result = subprocess.run(args, check=True)
            
            # Check the return code
            if result.returncode == 0:
                console.print(f"[bold green] Generated {output_path}")
            else:
                console.print(f"[bold red] Error:[bold red] Script {self.config.ior_2_csv} finished with a non-zero return code: {result.returncode}")                
                sys.exit(1)

        except subprocess.CalledProcessError as e:
            console.print(f"[bold red] Error:[bold red] Script execution failed: {e}")
            sys.exit(1)

    def full_report(self):        
        # Generate graphs
        self.plot_filesize_graph()
        self.plot_computing_graph()
        self.plot_striping_graph()

        #self.plot_graph(self.computing_df, "Computing Test")
        #self.plot_graph(self.striping_df, "Striping Test")

        # create the Jinja2 environment and load the template
        env = Environment(loader=FileSystemLoader(str(self.config.report_template.parent)))
        template = env.get_template(self.config.report_template.name)

        # Include any config information you'd like in the report
        # Include any config information you'd like in the report
        report_data = {            
            'graphs': [
                {"title": "File Size Test", "filename": self.filesize_png.name},
                {"title": "Computing Test", "filename": self.computing_png.name},
                {"title": "Striping Test", "filename": self.striping_png.name}
            ]
        }

        with open(self.report_html.as_posix(), "w") as f:
            f.write(template.render(report_data))
        
        console.print(f"[bold green]Report '{self.report_html}' generated successfully.\n")

config = IOPSConfig("/home/lgouveia/iops/config.ini")
report = BasicReport(0, config, config.workdir/"filesize_0", config.workdir/"computing_0", config.workdir/"striping_0")
report.full_report()


