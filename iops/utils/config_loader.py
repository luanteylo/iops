from dataclasses import dataclass
from typing import List
import configparser
from pathlib import Path


@dataclass
class NodesConfig:
    min_nodes: int
    max_nodes: int
    processes_per_node: int
    cores_per_node: int


@dataclass
class StorageConfig:
    filesystem_dir: str
    min_volume: int
    max_volume: int
    volume_step: int
    default_stripe: int
    stripe_folders: List[str]


@dataclass
class ExecutionConfig:
    test_type: str
    mode: str
    search_method: str
    job_manager: str
    benchmark_tool: str
    modules: str
    workdir: str
    repetitions: int
    status_check_delay: int
    wall_time: str
    tests: List[str]
    io_patterns: List[str]
    wait_range: List[int]


@dataclass
class TemplateConfig:
    bash_template: str
    report_template: str
    ior_2_csv: str


@dataclass
class IOPSConfig:
    nodes: NodesConfig
    storage: StorageConfig
    execution: ExecutionConfig
    template: TemplateConfig


class ConfigValidationError(Exception):
    pass


def _get_value(config: configparser.ConfigParser, section: str, key: str) -> str:
    value = config.get(section, key)
    return value.split("#")[0].strip() if "#" in value else value.strip()


def _is_power_of_two(n: int) -> bool:
    return (n > 0) and (n & (n - 1) == 0)


def load_config(config_path: Path) -> IOPSConfig:
    config = configparser.ConfigParser()
    config.read(config_path)

    nodes = NodesConfig(
        min_nodes=int(_get_value(config, "nodes", "min_nodes")),
        max_nodes=int(_get_value(config, "nodes", "max_nodes")),
        processes_per_node=int(_get_value(config, "nodes", "processes_per_node")),
        cores_per_node=int(_get_value(config, "nodes", "cores_per_node")),
    )

    storage = StorageConfig(
        filesystem_dir=_get_value(config, "storage", "filesystem_dir"),
        min_volume=int(_get_value(config, "storage", "min_volume")),
        max_volume=int(_get_value(config, "storage", "max_volume")),
        volume_step=int(_get_value(config, "storage", "volume_step")),
        default_stripe=int(_get_value(config, "storage", "default_stripe")),
        stripe_folders=[s.strip() for s in _get_value(config, "storage", "stripe_folders").split(",")]
    )

    execution = ExecutionConfig(
        test_type=_get_value(config, "execution", "test_type"),
        mode=_get_value(config, "execution", "mode"),
        search_method=_get_value(config, "execution", "search_method"),
        job_manager=_get_value(config, "execution", "job_manager"),
        benchmark_tool=_get_value(config, "execution", "benchmark_tool"),
        modules=_get_value(config, "execution", "modules"),
        workdir=_get_value(config, "execution", "workdir"),
        repetitions=int(_get_value(config, "execution", "repetitions")),
        status_check_delay=int(_get_value(config, "execution", "status_check_delay")),
        wall_time=_get_value(config, "execution", "wall_time"),
        tests=[t.strip() for t in _get_value(config, "execution", "tests").split(",")],
        io_patterns=[p.strip() for p in _get_value(config, "execution", "io_patterns").split(",")],
        wait_range=[int(x.strip()) for x in _get_value(config, "execution", "wait_range").split(",")]
    )

    template = TemplateConfig(
        bash_template=_get_value(config, "template", "bash_template"),
        report_template=_get_value(config, "template", "report_template"),
        ior_2_csv=_get_value(config, "template", "ior_2_csv")
    )

    return IOPSConfig(nodes, storage, execution, template)


def validate_config(config: IOPSConfig):
    if config.nodes.min_nodes <= 0:
        raise ConfigValidationError("min_nodes must be greater than 0")
    if config.nodes.max_nodes < config.nodes.min_nodes:
        raise ConfigValidationError("max_nodes must be >= min_nodes")
    if not _is_power_of_two(config.nodes.min_nodes):
        raise ConfigValidationError("min_nodes must be a power of 2")
    if not _is_power_of_two(config.nodes.max_nodes):
        raise ConfigValidationError("max_nodes must be a power of 2")

    if config.storage.min_volume <= 0:
        raise ConfigValidationError("min_volume must be greater than 0")
    if config.storage.max_volume < config.storage.min_volume:
        raise ConfigValidationError("max_volume must be >= min_volume")
    if not _is_power_of_two(config.storage.min_volume):
        raise ConfigValidationError("min_volume must be a power of 2")
    if not _is_power_of_two(config.storage.max_volume):
        raise ConfigValidationError("max_volume must be a power of 2")

    if config.execution.test_type not in {"write_only", "write_read"}:
        raise ConfigValidationError(f"Invalid test_type: {config.execution.test_type}")
    if config.execution.mode not in {"normal", "debug"}:
        raise ConfigValidationError(f"Invalid mode: {config.execution.mode}")
    if config.execution.repetitions <= 0:
        raise ConfigValidationError("repetitions must be greater than 0")
    if not config.execution.workdir:
        raise ConfigValidationError("execution.workdir must be specified")
    if not config.storage.stripe_folders:
        raise ConfigValidationError("At least one stripe folder must be provided")
