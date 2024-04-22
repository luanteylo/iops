import configparser
import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import pandas as pd

import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.ticker import MaxNLocator
import re

from iops.util.tags import TestType

class Generator:
    @staticmethod
    def ini_file(file_name):
        logging.info("Generating default configuration file...")
        config_nodes = configparser.ConfigParser()
        config_storage = configparser.ConfigParser()
        config_execution = configparser.ConfigParser()
        config_slurm = configparser.ConfigParser()

        config_template = configparser.ConfigParser()
    
        config_nodes['nodes'] = {
            'max_nodes': '32 # Max number of nodes that can be allocated (to limit computing tests)',
            'processes_per_node': '8 # The number of processes that will be used per node. For now, this is a static parameter',            
        }


        
        config_storage['storage'] = {
            'filesystem_dir': '/path/to/storage # The path to the directory where the benchmark tool will write/read from',                      
            'max_volume':  '34359738368 # Max volume size in bytes (to limit the size of the benchmarked file). Warning: the volume needs to be power of 2.',
            'stripe_folders': "ost_1, ost_2, ost_4, ost_8 # A list of folders with distinct striping setups.\n" \
            "# If 'None' is provided, the striping test will not be executed.\n" \
            "# For now, these folders need to be created manually inside the benchmark_output folder using the file system\n"\
            "# utility to define the correct striping setup. These folders need to be defined using a sequential number\n"\
            "# (the larger the number, the more OSTs); a good approach is to use the number of OSTs as this number.\n"\
            "# Otherwise, you may encounter problems in the striping graph.\n"
        }


        config_execution['execution'] = {
            'mode': 'fast | complete # Select the mode of execution',
            'search_method' :'greedy # The search method to be used. For now, only greedy is supported',
            'job_manager': 'slurm | local # Specify the job manager. If "local" is provided, the benchmark will be executed locally',
            'benchmark_tool': 'ior  # Specify the benchmark tool to use. For now, only IOR is supported.',            
            'modules': 'mpi, some_other_module | None # Specify the list of modules to load using "module add <module>". If "None" is provided, no modules are loaded',
            'workdir': '/path/to/workdir # # Specify the working directory, i.e., where the script files will be written',
            'repetitions': '5 # The number of repetitions for each test',
            
        }

        config_template['template'] = {
            'slurm_template': 'iops/templates/slurm_template.sh.j2 | None # If using Slurm, define the template file to generate the bash scripts. Otherwise, None.',
            'local_template': 'iops/templates/local_template.sh.j2 | None # Template for the bash script to be executed locally.',
            'report_template': 'iops/templates/report_template.html # Template for the report HTML page.',
            'ior_2_csv': 'tools/ior_2_csv.py # Path to the ior_2_csv.py script.',            
        }

        config_slurm['slurm'] = {
            'slurm_constraint': 'constraint_1, constraint_2 | None # Some clusters use the slurm constraint parameter (-c) to define the resources. If that is your case, set the list of constraints here, otherwise put None',
            'slurm_partition' : 'None # The partition to be used. If None, no partition is defined',
            'slurm_time' : 'None # The maximum time for the job. If None, no time is defined'
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

            config_file.write("# Slurm parameters (only used if slurm is selected as the job manager)\n")
            config_slurm.write(config_file)

        
        logging.info(f"Default configuration file generated as {file_name}")
    
    @staticmethod
    def from_template(template_path: Path, output_path: Path, info: dict ) -> None: # | list[dict]
        '''
        Generates a file from a give template
        '''
        # create the Jinja2 environment and load the template
        env = Environment(loader=FileSystemLoader(str(template_path.parent)))
        template = env.get_template(template_path.name)
        # generate the script
        rendered_file = template.render(**info)
        # write the script to a file
        with open(output_path, 'w') as f:
            f.write(rendered_file)
    

class Graphs:

    @staticmethod
    def __filesize(df: pd.DataFrame, output_path: Path) -> bool:
        try:
            # Consistency check
            expected_unique_values = 1
            for column in ['nodes', 'tasks', 'access', 'clients_per_node']:
                if df[column].nunique() != expected_unique_values:
                    raise ValueError(f"Column {column} does not have consistent values")

            # Retrieving consistent values
            nodes = df['nodes'].iloc[0]
            tasks = df['tasks'].iloc[0]
            access = df['access'].iloc[0]
            clients_per_node = df['clients_per_node'].iloc[0]
            
            # Label text
            graph_label = f"Nodes: {nodes}, Tasks: {tasks}, Operation: {access}, Processes/Node: {clients_per_node}"

            plt.figure(figsize=(12, 8))

            # Data processing for plotting
            df['aggregate_filesize_mb'] = df['aggregate_filesize'] / 2**20

            sns.lineplot(x='aggregate_filesize_mb', y='bw', data=df,
                        linewidth=2.5, color='royalblue', marker='o', markersize=8, linestyle='-', errorbar='sd')

            sns.scatterplot(x='aggregate_filesize_mb', y='bw', data=df,
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
            plt.savefig(output_path, format='svg')
            plt.close()
            return True
        except Exception as e:
            raise Exception(f"Error: {e}")
    
    @staticmethod
    def __computing(df: pd.DataFrame, output_path: Path) -> bool:
        try:
            # Consistency check
            expected_unique_values = 1
            for column in ['access', 'clients_per_node', 'aggregate_filesize']:
                if df[column].nunique() != expected_unique_values:
                    raise ValueError(f"Column {column} does not have consistent values")

            # Retrieving consistent values
            access = df['access'].iloc[0]
            clients_per_node = df['clients_per_node'].iloc[0]
            aggregate_filesize_bytes = df['aggregate_filesize'].iloc[0]
            aggregate_filesize_gb = aggregate_filesize_bytes / 2**30  # Convert bytes to GB

            # Label text
            graph_label = f"Operation: {access}, Processes/Node: {clients_per_node}, Aggregate File Size: {aggregate_filesize_gb:.2f} GB"

            plt.figure(figsize=(12, 8))

            sns.lineplot(x='nodes', y='bw', data=df,
                        linewidth=2.5, color='royalblue', marker='o', markersize=8, linestyle='-', errorbar='sd')

            sns.scatterplot(x='nodes', y='bw', data=df,
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
            plt.savefig(output_path, format='svg')
            plt.close()
            return True
        except Exception as e:
            raise Exception(f"Error: {e}")
    
    @staticmethod
    def __striping(df: pd.DataFrame, output_path: Path) -> bool:
        try:
            expected_unique_values = 1
            for column in ['access', 'nodes', 'tasks', 'clients_per_node', 'aggregate_filesize']:
                if df[column].nunique() != expected_unique_values:
                    raise ValueError(f"Column {column} does not have consistent values")

            # Retrieving consistent values
            access = df['access'].iloc[0]
            nodes = df['nodes'].iloc[0]
            tasks = df['tasks'].iloc[0]
            clients_per_node = df['clients_per_node'].iloc[0]
            aggregate_filesize_bytes = df['aggregate_filesize'].iloc[0]
            aggregate_filesize_gb = aggregate_filesize_bytes / 2**30  # Convert bytes to GB

            # Label text
            graph_label = f"Operation: {access}, Nodes: {nodes}, Tasks: {tasks}, Processes/Node: {clients_per_node}, Aggregate File Size: {aggregate_filesize_gb:.2f} GB"

            plt.figure(figsize=(12, 8))  # Increased size for better visibility
            
            # Extracting folder names
            df['striping'] = df['path'].apply(lambda x: Path(x).parent.name)
            
            # Extracting the numeric portion from the folder names
            df['order'] = df['striping'].apply(lambda x: int(re.search(r'\d+', x).group()))
            
            # Sorting the DataFrame based on the numeric portion
            df = df.sort_values(by='order')
            
            # Customized line plot
            sns.lineplot(x='striping', y='bw', data=df,
                        linewidth=2.5, color='royalblue', marker='o',
                        markersize=8, linestyle='-', errorbar='sd')
            
            # Scatter plot to add individual points
            sns.scatterplot(x='striping', y='bw', data=df,
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
            plt.savefig(output_path, format='svg')
            plt.close()
            return True
        except Exception as e:            
            raise Exception(f"Error: {e}")
        
    @staticmethod
    def generate(df: pd.DataFrame, graphfile: Path, test_type: TestType) -> None:
        '''
        Generates a graph based on the test type.
        '''
        try:
            if test_type == TestType.FILESIZE:
                return Graphs.__filesize(df, graphfile)
            elif test_type == TestType.COMPUTING:
                return Graphs.__computing(df, graphfile)
            elif test_type == TestType.STRIPING:
                return Graphs.__striping(df, graphfile)
            else:
                raise ValueError(f"Invalid test type: {test_type}")
        except Exception as e:
            raise Exception(f"Error: {e}")