import configparser
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import pandas as pd


from matplotlib import pyplot as plt
import matplotlib as mpl
import seaborn as sns
from matplotlib.ticker import MaxNLocator
import re

from iops.util.tags import TestType, VolumeValidation


# set the backend to Agg to avoid the need for a display
# when running on a headless server
mpl.use('Agg')


class Generator:
    @staticmethod
    def ini_file(file_name):
        config_nodes = configparser.ConfigParser()
        config_storage = configparser.ConfigParser()
        config_execution = configparser.ConfigParser()
        config_slurm = configparser.ConfigParser()
        config_template = configparser.ConfigParser()
    
        config_nodes['nodes'] = {
            'min_nodes': '1 # Minimum number of nodes that can be allocated (limits computing tests). Must be a power of 2',
            'max_nodes': '32 # Maximum number of nodes that can be allocated (limits computing tests). Must be a power of 2',
            'processes_per_node': '8 # Number of processes per node. Currently, this is a static parameter',            
        }

        config_storage['storage'] = {
            'filesystem_dir': '/path/to/storage # Directory where the benchmark tool will read/write data', 
            'min_volume': '1024  # Minimum volume size in megabytes. Must be a power of 2 and less than max_volume',
            'max_volume':  '8192 # Maximum volume size in megabytes (limits the size of the benchmarked file). Must be a power of 2.',
            'volume_step': f'1024 # Step size for increasing volume in megabytes. Accepted values are: {VolumeValidation.VALID_VOLUME_STEPS}\n',
            'stripe_folders': "ost_1, ost_2, ost_4, ost_8 # List of folders with different striping setups.\n" \
            "# If 'None' is provided, the striping test will not be executed.\n" \
            "# These folders should be created manually inside the benchmark_output directory using the file system utility\n"\
            "# to set the correct striping setup. The folders should be sequentially numbered (higher numbers imply more OSTs).\n"\
            "# Using the number of OSTs as the folder name is a good practice. Improper setup may cause striping graph issues.\n"
        }

        config_execution['execution'] = {
            'mode': 'normal # Execution mode. Use "normal" to generate and execute the benchmark scripts, or "debug" to generate the scripts without executing them',
            'search_method' :'greedy # Search method to use. Currently, only greedy is supported',
            'job_manager': ' slurm # Specify the job manager. Use "local" for local execution',
            'benchmark_tool': 'ior  # Benchmark tool to use. Currently, only IOR is supported.',            
            'modules': ' None # List of modules to load using "module add <module>". Use "None" to load no modules',
            'workdir': '/path/to/workdir # Directory where the script files will be written',
            'repetitions': '5 # Number of repetitions for each test',            
            'tests': 'filesize, computing, striping # List of tests to execute. Supported tests: filesize, computing, striping',            
            'io_patterns': 'sequential:shared, random:shared # List of IO patterns to execute. Each pattern is defined by access_pattern:file_access.\n' \
            '             # Access pattern can be sequential or random. File access can be single (one file per process) or shared (all processes access the same file).\n' \
            '             # Each test will be executed with the defined IO patterns. If multiple patterns are defined, tests will be repeated for each pattern.\n'
        }

        config_template['template'] = {
            'slurm_template': 'iops/templates/slurm_template.sh.j2 # Template file for Slurm to generate bash scripts. Use None if not using Slurm.',
            'local_template': 'iops/templates/local_template.sh.j2 # Template for the bash script for local execution.',
            'report_template': 'iops/templates/report_template.html # Template for the report HTML page.',
            'ior_2_csv': 'tools/ior_2_csv.py # Path to the ior_2_csv.py script.',            
        }

        config_slurm['slurm'] = {
            'slurm_constraint': 'None # Slurm constraint parameter (-c) for resource definition. Set list of constraints if applicable, otherwise use None',
            'slurm_partition' : 'None # Partition to use. Use None if no partition is specified',
            'slurm_time' : 'None # Maximum job time. Use None if no time limit is specified'
        }

        with open(file_name, 'w') as config_file:
            config_file.write("# This is the default configuration file for IOPS.\n")        
            config_file.write("# Edit this file to suit your needs.\n\n")
            config_nodes.write(config_file)
            config_storage.write(config_file)

            config_file.write("# Execution mode\n")
            config_file.write("# - normal: Generates and executes the benchmark scripts\n")
            config_file.write("# - debug: Generates but does not execute the benchmark scripts. Use to test the script generation.\n")
            config_file.write("# The debug mode can also be use to generate reports from existing data.\n")
            config_execution.write(config_file)
            
            config_file.write("# Templates and scripts \n")
            config_template.write(config_file)

            config_file.write("# Slurm parameters (only used if Slurm is selected as the job manager)\n")
            config_slurm.write(config_file)


    @staticmethod
    def from_template(template_path: Path, output_path: Path, info: dict ) -> None | list[dict]: #
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
                    if df[column].nunique() == 0:
                        raise ValueError(f"Column '{column}' has no values.")
                    else:
                        raise ValueError(f"Column '{column}' does not have consistent values.")

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

            #fixed maximum limit for y-axis
            max_bw = df['bw'].max() + 1000
            plt.ylim(0, max_bw)

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
            raise e
    
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
        
        if test_type == TestType.FILESIZE:
            return Graphs.__filesize(df, graphfile)
        elif test_type == TestType.COMPUTING:
            return Graphs.__computing(df, graphfile)
        elif test_type == TestType.STRIPING:
            return Graphs.__striping(df, graphfile)
        else:
            raise ValueError(f"Invalid test type: {test_type}")
    