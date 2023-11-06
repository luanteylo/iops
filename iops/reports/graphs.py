from pathlib import Path
import pandas as pd

import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.ticker import MaxNLocator
import re

from rich.console import Console

console = Console()

class Graph:

    @staticmethod
    def filesize(df: pd.DataFrame, output_path: Path) -> bool:
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
            console.print(f"[bold red] Error:[bold red] {e}")        
            return False
    
    @staticmethod
    def computing(df: pd.DataFrame, output_path: Path) -> bool:
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
            console.print(f"[bold red] Error:[bold red] {e}")        
            return False
    
    @staticmethod
    def striping(df: pd.DataFrame, output_path: Path) -> bool:
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
            console.print(f"[bold red] Error:[bold red] {e}")        
            return False