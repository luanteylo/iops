from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path
import yaml
import os
import shutil

@dataclass
class NodesConfig:
    min_nodes: int
    max_nodes: int
    node_step: int
    nodes_range: Optional[List[int]]
    processes_per_node: int
    processes_per_node_range: Optional[List[int]]
    cores_per_node: int


@dataclass
class StorageConfig:
    filesystem_dir: Path
    min_volume: int
    max_volume: int
    volume_step: int
    volume_range: Optional[List[int]]
    default_stripe: int
    stripe_folders: List[Path]


@dataclass
class ExecutionConfig:
    test_type: str    
    search_method: str
    job_manager: str
    benchmark_tool: str    
    workdir: Path
    repetitions: int
    status_check_delay: int
    wall_time: str
    tests: List[str]
    io_pattern: str 

@dataclass
class EnvironmentConfig:
    bash_template: Path
    sqlite_db: Optional[Path] 
    machine_name: Optional[str] 


@dataclass
class IOPSConfig:
    nodes: NodesConfig
    storage: StorageConfig
    execution: ExecutionConfig
    environment: EnvironmentConfig
    
    def to_dictionary(self) -> dict:
        """
        Convert the IOPSConfig dataclass to a dictionary.
        """
        return {
            "nodes": self.nodes.__dict__,
            "storage": {
                **self.storage.__dict__,
                "filesystem_dir": str(self.storage.filesystem_dir),
                "stripe_folders": [str(sf) for sf in self.storage.stripe_folders]
            },
            "execution": {
                **self.execution.__dict__,
                "workdir": str(self.execution.workdir),
                "bash_template": str(self.environment.bash_template),
                "sqlite_db": str(self.environment.sqlite_db) if self.environment.sqlite_db else None
            }
        }

class ConfigValidationError(Exception):
    pass


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(p)).expanduser().resolve()


def load_config(config_path: Path) -> IOPSConfig:
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    fs_dir = _expand(data["storage"]["filesystem_dir"])
    # get machine name from OS

    machine_name = os.uname().nodename if hasattr(os, 'uname') else os.environ.get('HOSTNAME', 'unknown')

    
    nodes_dict = dict(data["nodes"])
    volumes_dict = dict(data["storage"])
    # handle where nodes min, max, step are given or nodes_range is given
    if "nodes_range" in data["nodes"]:
        nodes_dict["nodes_range"] = data["nodes"]["nodes_range"]
        # nodes_dict.pop("min_nodes", None)
        # nodes_dict.pop("max_nodes", None)
        # nodes_dict.pop("node_step", None)
    elif "min_nodes" in data["nodes"]:
        nodes_dict["min_nodes"] = data["nodes"]["min_nodes"]
    elif "max_nodes" in data["nodes"]:
        nodes_dict["max_nodes"] = data["nodes"]["max_nodes"]
    elif "node_step" in data["nodes"]:
        nodes_dict["node_step"] = data["nodes"]["node_step"]
    if nodes_dict.get("nodes_range") is None:
        nodes_dict["nodes_range"] = list(range(
            data["nodes"]["min_nodes"],
            data["nodes"]["max_nodes"] + 1,
            data["nodes"]["node_step"]
        ))
    # handle processes_per_node similarly
    if "processes_per_node_range" in data["nodes"]:
        nodes_dict["processes_per_node_range"] = data["nodes"]["processes_per_node_range"]
    elif "processes_per_node" in data["nodes"]:
        nodes_dict["processes_per_node"] = data["nodes"]["processes_per_node"]
    if nodes_dict.get("processes_per_node_range") is None:
        nodes_dict["processes_per_node_range"] = [data["nodes"]["processes_per_node"]]
    
    # handle volume_range similarly
    if "volume_range" in data["storage"]:
        volumes_dict["volume_range"] = data["storage"]["volume_range"]
        # data["storage"].pop("min_volume", None)
        # data["storage"].pop("max_volume", None)
        # data["storage"].pop("volume_step", None)
    elif "min_volume" in data["storage"]:
        volumes_dict["min_volume"] = data["storage"]["min_volume"]
    elif "max_volume" in data["storage"]:
        volumes_dict["max_volume"] = data["storage"]["max_volume"]
    elif "volume_step" in data["storage"]:
        volumes_dict["volume_step"] = data["storage"]["volume_step"]
    if volumes_dict.get("volume_range") is None:
        volumes_dict["volume_range"] = list(range(
            data["storage"]["min_volume"],
            data["storage"]["max_volume"] + 1,
            data["storage"]["volume_step"]
        ))

    return IOPSConfig(
        nodes=NodesConfig(**nodes_dict),
        storage=StorageConfig(
            filesystem_dir=fs_dir,
            min_volume=data["storage"]["min_volume"],
            max_volume=data["storage"]["max_volume"],            
            volume_step=data["storage"]["volume_step"],
            volume_range=volumes_dict["volume_range"],
            default_stripe=data["storage"]["default_stripe"],
            stripe_folders=[fs_dir / Path(entry) for entry in data["storage"]["stripe_folders"]],
        ),
        execution=ExecutionConfig(
            test_type=data["execution"]["test_type"],            
            search_method=data["execution"]["search_method"],
            job_manager=data["execution"]["job_manager"],
            benchmark_tool=data["execution"]["benchmark_tool"],            
            workdir=_expand(data["execution"]["workdir"]),
            repetitions=data["execution"]["repetitions"],
            status_check_delay=data["execution"]["status_check_delay"],
            wall_time=data["execution"]["wall_time"],
            tests=data["execution"]["tests"],
            io_pattern=data["execution"]["io_pattern"],            
        ),
        environment=EnvironmentConfig(
            bash_template=_expand(data["environment"]["bash_template"]),
            sqlite_db=_expand(data["environment"].get("sqlite_db", "iops.db")),
            machine_name=machine_name,
        ),
    )


def validate_config(config: IOPSConfig):
    if not config.nodes:
        raise ConfigValidationError("Nodes configuration is missing")
    if not config.nodes.nodes_range:
        if config.nodes.min_nodes <= 0:
            raise ConfigValidationError("min_nodes must be greater than 0")
        if config.nodes.max_nodes < config.nodes.min_nodes:
            raise ConfigValidationError("max_nodes must be >= min_nodes")

        if config.nodes.node_step <= 0:
            raise ConfigValidationError("node_step must be greater than 0")
        #if not _is_power_of_two(config.nodes.min_nodes):
        #    raise ConfigValidationError("min_nodes must be a power of 2")
        #if not _is_power_of_two(config.nodes.max_nodes):
        #    raise ConfigValidationError("max_nodes must be a power of 2")
    if not config.nodes.processes_per_node_range:
        if config.nodes.processes_per_node <= 0:
            raise ConfigValidationError("processes_per_node must be greater than 0")
        if config.nodes.processes_per_node > config.nodes.cores_per_node:
            raise ConfigValidationError("processes_per_node cannot exceed cores_per_node")
    if not config.storage:
        raise ConfigValidationError("Storage configuration is missing")
    if not config.storage.volume_range:
        if config.storage.min_volume <= 0:
            raise ConfigValidationError("min_volume must be greater than 0")
        if config.storage.max_volume < config.storage.min_volume:
            raise ConfigValidationError("max_volume must be >= min_volume")
        #if not _is_power_of_two(config.storage.min_volume):
        #    raise ConfigValidationError("min_volume must be a power of 2")
        #if not _is_power_of_two(config.storage.max_volume):
        #    raise ConfigValidationError("max_volume must be a power of 2")
    # else:
    #     if len(config.storage.volume_range) != 2:
    #         raise ConfigValidationError("volume_range must have exactly two elements: [min_volume, max_volume]")
        
    if config.execution.test_type not in {"write_only", "write_read"}:
        raise ConfigValidationError(f"Invalid test_type: {config.execution.test_type}")
    if config.execution.repetitions <= 0:
        raise ConfigValidationError("repetitions must be greater than 0")

    if not config.execution.workdir.exists():
        raise ConfigValidationError(f"execution.workdir does not exist: {config.execution.workdir}")
    if not config.execution.workdir.is_dir():
        raise ConfigValidationError("execution.workdir must be a directory")

    if not config.storage.filesystem_dir.exists():
        raise ConfigValidationError(f"filesystem_dir does not exist: {config.storage.filesystem_dir}")
    if not config.storage.filesystem_dir.is_dir():
        raise ConfigValidationError("filesystem_dir must be a directory")

    if not config.storage.stripe_folders:
        raise ConfigValidationError("At least one stripe folder must be provided")
    for sf in config.storage.stripe_folders:
        if not sf.exists():
            raise ConfigValidationError(f"Stripe folder does not exist: {sf.name}")
        if not sf.is_dir():
            raise ConfigValidationError(f"Stripe folder is not a directory: {sf.name}")     
        
    # if benchmark is IOR, validate specific parameters
    if config.execution.benchmark_tool.lower() == "ior":
        if not config.execution.tests:
            raise ConfigValidationError("At least one test must be specified for IOR benchmark")
        if not config.execution.io_pattern:
            raise ConfigValidationError("An IO pattern must be specified for the IOR benchmark")
        if config.execution.io_pattern not in {"sequential:shared", "random:shared", "sequential:single", "random:single"}:
            raise ConfigValidationError(f"Invalid IO pattern for IOR: {config.execution.io_pattern}")
        for test in config.execution.tests:
            if test not in {"nodes", "volume", "ost_count", "processes_per_node"}:
                raise ConfigValidationError(f"Invalid test type for IOR: {test}")
            
        ior_path = shutil.which("ior")
        if not ior_path:
            raise ConfigValidationError("IOR benchmark tool is not installed or not found in PATH")
        
    if not config.environment.bash_template.exists():
        raise ConfigValidationError(f"bash_template file does not exist: {config.environment.bash_template}")
    if not config.environment.bash_template.is_file():
        raise ConfigValidationError(f"bash_template path is not a file: {config.environment.bash_template}")
    

                
    # check if job manager is valid
    valid_job_managers = {"slurm", "local"}
    if config.execution.job_manager not in valid_job_managers:
        raise ConfigValidationError(f"Invalid job manager: {config.execution.job_manager}. Must be one of {valid_job_managers}")
    # check if search method is valid
    valid_search_methods = {"greedy", "exhaustive", "bayesian"}
    if config.execution.search_method not in valid_search_methods:
        raise ConfigValidationError(f"Invalid search method: {config.execution.search_method}. Must be one of {valid_search_methods}")


