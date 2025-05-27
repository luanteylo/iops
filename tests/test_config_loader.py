import pytest
from pathlib import Path
from iops.utils.config_loader import load_config, IOPSConfig


sample_ini_content = """
[nodes]
min_nodes = 2
max_nodes = 4
processes_per_node = 8
cores_per_node = 32

[storage]
filesystem_dir = /tmp
min_volume = 1024
max_volume = 2048
volume_step = 1024
default_stripe = 0
stripe_folders = folder1, folder2, folder3, folder4

[execution]
test_type = write_only
mode = normal
search_method = greedy
job_manager = local
benchmark_tool = ior
modules = None
workdir = /tmp/work
repetitions = 5
status_check_delay = 10
wall_time = 00:30:00
tests = filesize, computing
io_patterns = sequential:shared, random:shared
wait_range = 0, 0

[template]
bash_template = /templates/bash.sh
report_template = /templates/report.html
ior_2_csv = /tools/ior_2_csv.py
"""


def test_config_loader_parses_ini_correctly(tmp_path):
    ini_path = tmp_path / "sample.ini"
    ini_path.write_text(sample_ini_content)

    config: IOPSConfig = load_config(ini_path)

    assert config.nodes.min_nodes == 2
    assert config.nodes.max_nodes == 4
    assert config.storage.filesystem_dir == "/tmp"
    assert config.execution.job_manager == "local"
    assert config.execution.tests == ["filesize", "computing"]
    assert config.execution.io_patterns == ["sequential:shared", "random:shared"]
    assert config.execution.wait_range == [0, 0]
    assert config.template.bash_template == "/templates/bash.sh"
