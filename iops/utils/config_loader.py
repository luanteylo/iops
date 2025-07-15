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
    processes_per_node: int
    cores_per_node: int


@dataclass
class StorageConfig:
    filesystem_dir: Path
    min_volume: int
    max_volume: int
    volume_step: int
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


@dataclass
class IOPSConfig:
    nodes: NodesConfig
    storage: StorageConfig
    execution: ExecutionConfig
    environment: EnvironmentConfig



class ConfigValidationError(Exception):
    pass


def _is_power_of_two(n: int) -> bool:
    return (n > 0) and (n & (n - 1) == 0)


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(p)).expanduser().resolve()


def load_config(config_path: Path) -> IOPSConfig:
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    fs_dir = _expand(data["storage"]["filesystem_dir"])

    return IOPSConfig(
        nodes=NodesConfig(**data["nodes"]),
        storage=StorageConfig(
            filesystem_dir=fs_dir,
            min_volume=data["storage"]["min_volume"],
            max_volume=data["storage"]["max_volume"],            
            volume_step=data["storage"]["volume_step"],
            default_stripe=data["storage"]["default_stripe"],
            stripe_folders=[fs_dir/ Path(entry) for entry in data["storage"]["stripe_folders"]],
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
        ),
    )


def validate_config(config: IOPSConfig):
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

    if config.storage.min_volume <= 0:
        raise ConfigValidationError("min_volume must be greater than 0")
    if config.storage.max_volume < config.storage.min_volume:
        raise ConfigValidationError("max_volume must be >= min_volume")
    #if not _is_power_of_two(config.storage.min_volume):
    #    raise ConfigValidationError("min_volume must be a power of 2")
    #if not _is_power_of_two(config.storage.max_volume):
    #    raise ConfigValidationError("max_volume must be a power of 2")

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
        if config.execution.io_pattern not in {"sequential:shared", "random:shared"}:
            raise ConfigValidationError(f"Invalid IO pattern for IOR: {config.execution.io_pattern}")
        for test in config.execution.tests:
            if test not in {"nodes", "volume", "ost_count"}:
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


def to_dictionary(config: IOPSConfig) -> dict:
    """
    Convert the IOPSConfig dataclass to a dictionary.
    """
    return {
        "nodes": config.nodes.__dict__,
        "storage": {
            **config.storage.__dict__,
            "filesystem_dir": str(config.storage.filesystem_dir),
            "stripe_folders": [str(sf) for sf in config.storage.stripe_folders]
        },
        "execution": {
            **config.execution.__dict__,
            "workdir": str(config.execution.workdir),
            "bash_template": str(config.environment.bash_template),
            "sqlite_db": str(config.environment.sqlite_db) if config.environment.sqlite_db else None
        }
    }