import configparser
import re

VALID_FILE_SYSTEMS = {"lustre", "beegfs"}  # Add other allowed file systems if needed
VALID_MODES = {"fast", "complete"}  # Add other allowed modes if needed

class IOPSConfig:
    def __init__(self, config_path):
        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        
        self.load_nodes()
        self.load_storage()
        self.load_execution()

    def __get(self, section, key):
        value = self.config.get(section, key)
        if "#" in value:
            value = value.split("#")[0].strip()
        return value
        
    def load_nodes(self):
        nodes_str = self.__get("nodes", "nodes")
        self.nodes = self.parse_nodes(nodes_str)
        self.max_nodes = int(self.__get("nodes", "max_nodes"))
        self.max_processes_per_node = int(self.__get("nodes", "max_processes_per_node"))

    def load_storage(self):
        self.path = self.__get("storage", "path")
        self.max_ost = int(self.__get("storage", "max_ost"))
        self.default_stripe_count = int(self.__get("storage", "default_stripe_count"))
        self.default_stripe_size = int(self.__get("storage", "default_stripe_size"))        
        self.file_system = self.__get("storage", "file_system")

        if self.file_system not in VALID_FILE_SYSTEMS:
            raise ValueError(f"Invalid file_system: {self.file_system}. Allowed values are {', '.join(VALID_FILE_SYSTEMS)}")
        
    def load_execution(self):
        self.mode = self.__get("execution", "mode")

        if self.mode not in VALID_MODES:
            raise ValueError(f"Invalid mode: {self.mode}. Allowed values are {', '.join(VALID_MODES)}")

        
    def parse_nodes(self, nodes_str):
        nodes_list = []
        patterns = re.findall(r"([a-zA-Z0-9]+)\[([^\]]+)\]|([a-zA-Z0-9]+)", nodes_str)
        
        for pattern in patterns:
            prefix, range_str, single_node = pattern
            if prefix:
                # Split by comma inside the range
                for subrange in range_str.split(","):
                    subrange = subrange.strip()
                    
                    # Check if the subrange is a simple number or a range
                    if "-" in subrange:
                        start, end = map(int, subrange.split("-"))
                        for i in range(start, end + 1):
                            nodes_list.append(f"{prefix}{i}")
                    else:
                        nodes_list.append(f"{prefix}{subrange}")
            else:
                nodes_list.append(single_node)
        return nodes_list
    
    def __str__(self):
        lines = []
        lines.append("IOPS Configuration:")
        
        # Nodes section
        lines.append(f"  \t\tNodes: {self.nodes}")
        lines.append(f"  \t\tMax Nodes: {self.max_nodes}")
        lines.append(f"  \t\tMax Processes Per Node: {self.max_processes_per_node}")
        
        # Storage section
        lines.append(f"  \t\tStorage Path: {self.path}")
        lines.append(f"  \t\tMax OST: {self.max_ost}")
        lines.append(f"  \t\tDefault Stripe Count: {self.default_stripe_count}")
        lines.append(f"  \t\tDefault Stripe Size: {self.default_stripe_size} bytes")
        lines.append(f"  \t\tFile System: {self.file_system}")

        # Execution section
        lines.append(f"  \t\tExecution Mode: {self.mode}")

        return "\n".join(lines)


