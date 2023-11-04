import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from matplotlib.ticker import MaxNLocator
import subprocess
import re
from rich.console import Console
import sys 
from iops.setup.iops_config import IOPSConfig
import shutil

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

        self.filesize_fig = self.report_dir / f"filesize_{self.report_id}.svg"
        self.computing_fig = self.report_dir / f"computing_{self.report_id}.svg"
        self.striping_fig = self.report_dir /  f"striping_{self.report_id}.svg"

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
        # Consistency check
        expected_unique_values = 1
        for column in ['nodes', 'tasks', 'access', 'clients_per_node']:
            if self.filesize_df[column].nunique() != expected_unique_values:
                raise ValueError(f"Column {column} does not have consistent values")

        # Retrieving consistent values
        nodes = self.filesize_df['nodes'].iloc[0]
        tasks = self.filesize_df['tasks'].iloc[0]
        access = self.filesize_df['access'].iloc[0]
        clients_per_node = self.filesize_df['clients_per_node'].iloc[0]
        
        # Label text
        graph_label = f"Nodes: {nodes}, Tasks: {tasks}, Operation: {access}, Processes/Node: {clients_per_node}"

        plt.figure(figsize=(12, 8))

        # Data processing for plotting
        self.filesize_df['aggregate_filesize_mb'] = self.filesize_df['aggregate_filesize'] / 2**20

        sns.lineplot(x='aggregate_filesize_mb', y='bw', data=self.filesize_df,
                     linewidth=2.5, color='royalblue', marker='o', markersize=8, linestyle='-', errorbar='sd')

        sns.scatterplot(x='aggregate_filesize_mb', y='bw', data=self.filesize_df,
                        color='royalblue', marker='x', s=50)

        plt.grid(True, which='both', linestyle='--', linewidth=0.5)

        # Axis labels
        plt.xlabel('Aggregate File Size (MiB)', fontsize=14)
        plt.ylabel('Bandwidth (MB/s)', fontsize=14)

        # Ticks styling
        plt.xticks(fontsize=14)
        plt.yticks(fontsize=14)

        # Enhanced label styling and positioning
        label_style = {
            'fontsize': 12,
            'color': 'dimgrey',
            'fontweight': 'bold',
            'bbox': dict(boxstyle="round,pad=0.5", edgecolor='lightgrey', facecolor='whitesmoke')
        }
        # Position the label inside the lower right of the plot area
        plt.text(0.95, 0.02, graph_label, transform=plt.gca().transAxes,
                 horizontalalignment='right', verticalalignment='bottom', **label_style)

        # Save the figure
        plt.savefig(self.filesize_fig, format='svg')
        plt.close()

    def plot_computing_graph(self):
        # Consistency check
        expected_unique_values = 1
        for column in ['access', 'clients_per_node', 'aggregate_filesize']:
            if self.computing_df[column].nunique() != expected_unique_values:
                raise ValueError(f"Column {column} does not have consistent values")

        # Retrieving consistent values
        access = self.computing_df['access'].iloc[0]
        clients_per_node = self.computing_df['clients_per_node'].iloc[0]
        aggregate_filesize_bytes = self.computing_df['aggregate_filesize'].iloc[0]
        aggregate_filesize_gb = aggregate_filesize_bytes / 2**30  # Convert bytes to GB

        # Label text
        graph_label = f"Operation: {access}, Processes/Node: {clients_per_node}, Aggregate File Size: {aggregate_filesize_gb:.2f} GB"

        plt.figure(figsize=(12, 8))

        sns.lineplot(x='nodes', y='bw', data=self.computing_df,
                     linewidth=2.5, color='royalblue', marker='o', markersize=8, linestyle='-', errorbar='sd')

        sns.scatterplot(x='nodes', y='bw', data=self.computing_df,
                        color='royalblue', marker='x', s=50)

        plt.grid(True, which='both', linestyle='--', linewidth=0.5)

        plt.xlabel('Number of Computing Nodes', fontsize=14)
        plt.ylabel('Bandwidth (MB/s)', fontsize=14)

        plt.xticks(fontsize=14)
        plt.yticks(fontsize=14)

        plt.gca().xaxis.set_major_locator(MaxNLocator(integer=True))

        # Enhanced label styling and positioning
        label_style = {
            'fontsize': 12,
            'color': 'dimgrey',
            'fontweight': 'bold',
            'bbox': dict(boxstyle="round,pad=0.5", edgecolor='lightgrey', facecolor='whitesmoke')
        }
        # Position the label inside the lower right of the plot area
        plt.text(0.95, 0.02, graph_label, transform=plt.gca().transAxes,
                 horizontalalignment='right', verticalalignment='bottom', **label_style)

        # Save the figure
        plt.savefig(self.computing_fig, format='svg')
        plt.close()
   
    
    def plot_striping_graph(self):
        
        expected_unique_values = 1
        for column in ['access', 'nodes', 'tasks', 'clients_per_node', 'aggregate_filesize']:
            if self.striping_df[column].nunique() != expected_unique_values:
                raise ValueError(f"Column {column} does not have consistent values")

        # Retrieving consistent values
        access = self.striping_df['access'].iloc[0]
        nodes = self.striping_df['nodes'].iloc[0]
        tasks = self.striping_df['tasks'].iloc[0]
        clients_per_node = self.striping_df['clients_per_node'].iloc[0]
        aggregate_filesize_bytes = self.striping_df['aggregate_filesize'].iloc[0]
        aggregate_filesize_gb = aggregate_filesize_bytes / 2**30  # Convert bytes to GB

        # Label text
        graph_label = f"Operation: {access}, Nodes: {nodes}, Tasks: {tasks}, Processes/Node: {clients_per_node}, Aggregate File Size: {aggregate_filesize_gb:.2f} GB"

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
        #plt.title("Striping Test", fontsize=18, fontweight='bold')  # Increased font size and made bold
        plt.xlabel('Striping directory', fontsize=14)  # Increased font size
        plt.ylabel('Bandwidth (MB/s)', fontsize=14)  # Increased font size

        # Customizing axes ticks
        plt.xticks(fontsize=14)
        plt.yticks(fontsize=14)

        # Enhanced label styling and positioning
        label_style = {
            'fontsize': 12,
            'color': 'dimgrey',
            'fontweight': 'bold',
            'bbox': dict(boxstyle="round,pad=0.5", edgecolor='lightgrey', facecolor='whitesmoke')
        }
        # Position the label inside the lower right of the plot area
        plt.text(0.95, 0.02, graph_label, transform=plt.gca().transAxes,
                 horizontalalignment='right', verticalalignment='bottom', **label_style)

        #plt.show()
        plt.savefig(self.striping_fig, format='svg')
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
                {"title": "File Size Test", "filename": self.filesize_fig.name},
                {"title": "Computing Test", "filename": self.computing_fig.name},
                {"title": "Striping Test", "filename": self.striping_fig.name}
            ]
        }

        with open(self.report_html.as_posix(), "w") as f:
            f.write(template.render(report_data))
        
        console.print(f"[bold green]Report '{self.report_html}' generated successfully.\n")

