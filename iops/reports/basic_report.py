import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from iops.setup.iops_config import IOPSConfig

class BasicReport:

    def __init__(self, config : IOPSConfig, filesize_csv: Path, computing_csv: Path, striping_csv: Path):
        self.config = config
        self.filesize_df = pd.read_csv(filesize_csv)
        self.computing_df = pd.read_csv(computing_csv)
        self.striping_df = pd.read_csv(striping_csv)

    def plot_filesize_graph(self):
        plt.figure(figsize=(12, 8))  # Increased size for better visibility

        # Convert block size from bytes to megabytes
        report.filesize_df['aggregate_filesize'] = report.filesize_df['aggregate_filesize'] / (1024 * 1024)

        # Customized line plot
        sns.lineplot(x='aggregate_filesize', y='bw', data=report.filesize_df,
                    linewidth=2.5, color='royalblue', marker='o', markersize=8, linestyle='-')

        # Adding gridlines for better readability
        plt.grid(True, which='both', linestyle='--', linewidth=0.5)

        # Title and labels
        plt.title("FileSize Test", fontsize=18, fontweight='bold')  # Increased font size and made bold
        plt.xlabel('File Size (MB)', fontsize=14)  # Increased font size
        plt.ylabel('Bandwidth (MB/s)', fontsize=14)  # Increased font size

        # Customizing axes ticks
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)

        plt.savefig(Path(self.config.workdir, "filesize_graph.png"))
        plt.close()

    

    def full_report(self):
        # Generate graphs
        self.plot_filesize_graph()
        #self.plot_graph(self.computing_df, "Computing Test")
        #self.plot_graph(self.striping_df, "Striping Test")

        # create the Jinja2 environment and load the template
        env = Environment(loader=FileSystemLoader(str(self.config.report_template.parent)))
        template = env.get_template(self.config.report_template.name)

        # Include any config information you'd like in the report
        report_data = {
            'config_info': str(self.config),
            'graphs': ["File Size Test.png", "Computing Test.png", "Striping Test.png"]
        }

        with open(Path(self.config.workdir, 'report.html'), "w") as f:
            f.write(template.render(report_data))

config = IOPSConfig("/home/lgouveia/iops/default_config.ini")
report = BasicReport(config, Path(config.workdir, "filesize.csv"), Path(config.workdir, "computing.csv"), Path(config.workdir, "striping.csv") )
report.full_report()






#report.filesize_df