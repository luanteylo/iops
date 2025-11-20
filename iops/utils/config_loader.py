from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

import yaml
import os
import shutil

from iops.utils.logger import HasLogger

@dataclass
class NodesConfig:
    min_node: int
    max_node: int
    step_node: int
    node_range: Optional[List[int]]
    min_pp_node: int
    max_pp_node: int
    step_pp_node: int
    pp_node_range: Optional[List[int]]
    cores_per_node: int


@dataclass
class StorageConfig:
    filesystem_dir: Path
    min_volume: int
    max_volume: int
    step_volume: int
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

    def build_range(self):
        """ Build a range of values based on min, max, and step.
        for volume, nodes, etc.
        """
        try:
            if self.nodes.node_range is None:
                self.nodes.node_range = list(range(self.nodes.min_node, self.nodes.max_node + 1, self.nodes.step_node))
            if self.storage.volume_range is None:
                self.storage.volume_range = list(range(self.storage.min_volume, self.storage.max_volume + 1, self.storage.step_volume))
            if self.nodes.pp_node_range is None:
                self.nodes.pp_node_range = list(range(self.nodes.min_pp_node, self.nodes.max_pp_node + 1, self.nodes.step_pp_node))
        except Exception as e:
            raise ConfigValidationError(f"Error building ranges in configuration: {e}")    

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

    

    return IOPSConfig(
        nodes=NodesConfig(**data["nodes"]),
        storage=StorageConfig(
            filesystem_dir=fs_dir,
            min_volume=data["storage"]["min_volume"],
            max_volume=data["storage"]["max_volume"],            
            step_volume=data["storage"]["step_volume"],
            volume_range=data["storage"]["volume_range"],
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
    def _is_positive_int(value) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    def _ensure_positive_int(name: str, value):
        if value is None or not _is_positive_int(value):
            raise ConfigValidationError(f"{name} must be an integer greater than 0")

    def _ensure_int_list(name: str, seq):
        if not isinstance(seq, list) or not seq:
            raise ConfigValidationError(f"{name} must be a non-empty list of integers")
        for i, v in enumerate(seq):
            if not _is_positive_int(v):
                raise ConfigValidationError(f"{name}[{i}] must be an integer greater than 0")

    # Nodes block
    if config.nodes is None:
        raise ConfigValidationError("Nodes configuration is missing")

    if config.nodes.node_range is None:
        _ensure_positive_int("min_node", config.nodes.min_node)
        _ensure_positive_int("max_node", config.nodes.max_node)
        _ensure_positive_int("step_node", config.nodes.step_node)
        if config.nodes.max_node < config.nodes.min_node:
            raise ConfigValidationError("max_node must be >= min_node")
        # if not _is_power_of_two(config.nodes.min_node):
        #     raise ConfigValidationError("min_node must be a power of 2")
        # if not _is_power_of_two(config.nodes.max_node):
        #     raise ConfigValidationError("max_node must be a power of 2")
    else:
        _ensure_int_list("node_range", config.nodes.node_range)

    # Per-process-per-node (pp_node) block
    if config.nodes.pp_node_range is None:
        _ensure_positive_int("min_pp_node", config.nodes.min_pp_node)
        _ensure_positive_int("max_pp_node", config.nodes.max_pp_node)
        _ensure_positive_int("step_pp_node", config.nodes.step_pp_node)
        # cores = getattr(config.nodes, "cores_per_node", None)
        # if cores is None:
        #     raise ConfigValidationError("cores_per_node must be set when validating pp_node counts")
        # if config.nodes.max_pp_node > cores:
        #     raise ConfigValidationError("max_pp_node cannot exceed cores_per_node")
    else:
        _ensure_int_list("pp_node_range", config.nodes.pp_node_range)
        # cores = getattr(config.nodes, "cores_per_node", None)
        # if cores is not None:
        #     if any(pp > cores for pp in config.nodes.pp_node_range):
        #         raise ConfigValidationError("All values in pp_node_range cannot exceed cores_per_node")

    # Storage block
    if config.storage is None:
        raise ConfigValidationError("Storage configuration is missing")

    if config.storage.volume_range is None:
        _ensure_positive_int("min_volume", config.storage.min_volume)
        _ensure_positive_int("max_volume", config.storage.max_volume)
        _ensure_positive_int("step_volume", config.storage.step_volume)
        if config.storage.max_volume < config.storage.min_volume:
            raise ConfigValidationError("max_volume must be >= min_volume")
        #if not _is_power_of_two(config.storage.min_volume):
        #    raise ConfigValidationError("min_volume must be a power of 2")
        #if not _is_power_of_two(config.storage.max_volume):
        #    raise ConfigValidationError("max_volume must be a power of 2")
    else:
        _ensure_int_list("volume_range", config.storage.volume_range) 
    

    # Execution block
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
            if test not in {"node", "volume", "ost_count", "processes_per_node"}:
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


