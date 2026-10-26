"""
Tests for the multi-node probe launcher.

The samplers used to fan out only under SLURM, which meant a multi-node job on
any other scheduler (OAR, PBS) was traced on the head node alone. These tests
cover the shared launcher that resolves the node list and starts one sampler per
node, plus its integration with the resource and GPU samplers.
"""

import os
import pathlib
import subprocess

import pytest
import yaml

from conftest import load_config


def _write_script(path, content):
    path.write_text(content)
    path.chmod(0o755)
    return path


def _bash_syntax_ok(path):
    return subprocess.run(["bash", "-n", str(path)], capture_output=True).returncode == 0


# ============================================================================ #
# Launcher Template
# ============================================================================ #

class TestNodeLauncherTemplate:
    """Tests for the node launcher script template."""

    def test_template_is_valid_bash(self, tmp_path):
        from iops.execution.planner import NODE_LAUNCHER_TEMPLATE

        launcher = _write_script(tmp_path / "launcher.sh", NODE_LAUNCHER_TEMPLATE)
        assert _bash_syntax_ok(launcher)

    def test_template_defines_public_functions(self):
        from iops.execution.planner import NODE_LAUNCHER_TEMPLATE

        assert "_iops_node_list()" in NODE_LAUNCHER_TEMPLATE
        assert "_iops_remote_shell()" in NODE_LAUNCHER_TEMPLATE
        assert "_iops_launch_on_nodes()" in NODE_LAUNCHER_TEMPLATE

    def test_template_has_no_format_placeholders(self):
        """The launcher is written as-is, so single braces must be safe."""
        from iops.execution.planner import NODE_LAUNCHER_TEMPLATE

        # A stray {name} would raise KeyError if the template were ever formatted
        assert "{execution_dir}" not in NODE_LAUNCHER_TEMPLATE


# ============================================================================ #
# Node List Resolution
# ============================================================================ #

class TestNodeListResolution:
    """Tests for _iops_node_list across schedulers."""

    def _run_node_list(self, tmp_path, env):
        from iops.execution.planner import NODE_LAUNCHER_TEMPLATE

        launcher = _write_script(tmp_path / "launcher.sh", NODE_LAUNCHER_TEMPLATE)
        full_env = dict(os.environ)
        # Drop any scheduler variables inherited from the test host
        for key in ("SLURM_JOB_ID", "SLURM_JOB_NODELIST", "SLURM_NNODES",
                    "OAR_JOB_ID", "OAR_NODEFILE", "OAR_NODE_FILE", "PBS_NODEFILE"):
            full_env.pop(key, None)
        full_env.update(env)
        result = subprocess.run(
            ["bash", "-c", f'source "{launcher}"; _iops_node_list'],
            capture_output=True, text=True, env=full_env, timeout=10,
        )
        assert result.returncode == 0, result.stderr
        return [line for line in result.stdout.strip().split("\n") if line]

    def test_reads_oar_nodefile(self, tmp_path):
        nodefile = tmp_path / "oar_nodes"
        # OAR node files list one line per core, so duplicates must collapse
        nodefile.write_text("node-a\nnode-a\nnode-b\nnode-b\n")

        nodes = self._run_node_list(tmp_path, {"OAR_NODEFILE": str(nodefile)})
        assert nodes == ["node-a", "node-b"]

    def test_reads_pbs_nodefile(self, tmp_path):
        nodefile = tmp_path / "pbs_nodes"
        nodefile.write_text("node-1\nnode-2\n")

        nodes = self._run_node_list(tmp_path, {"PBS_NODEFILE": str(nodefile)})
        assert nodes == ["node-1", "node-2"]

    def test_falls_back_to_local_host(self, tmp_path):
        nodes = self._run_node_list(tmp_path, {})
        assert len(nodes) == 1
        assert nodes[0]

    def test_falls_back_when_nodefile_unreadable(self, tmp_path):
        nodes = self._run_node_list(
            tmp_path, {"OAR_NODEFILE": str(tmp_path / "does_not_exist")}
        )
        assert len(nodes) == 1
        assert nodes[0]


# ============================================================================ #
# Fan-out Behaviour
# ============================================================================ #

class TestLauncherFanOut:
    """Behavioural tests for _iops_launch_on_nodes."""

    def _sampler_files(self, tmp_path, interval=0.05):
        from iops.execution.planner import (
            EXIT_HANDLER_TEMPLATE, NODE_LAUNCHER_TEMPLATE, RESOURCE_SAMPLER_TEMPLATE,
            TRACE_FILENAME_PREFIX, SAMPLER_SENTINEL_FILENAME,
        )

        _write_script(tmp_path / "handler.sh", EXIT_HANDLER_TEMPLATE)
        _write_script(tmp_path / "launcher.sh", NODE_LAUNCHER_TEMPLATE)
        _write_script(tmp_path / "sampler.sh", RESOURCE_SAMPLER_TEMPLATE.format(
            execution_dir=str(tmp_path),
            trace_prefix=TRACE_FILENAME_PREFIX,
            trace_interval=interval,
            sentinel_filename=SAMPLER_SENTINEL_FILENAME,
        ))
        return TRACE_FILENAME_PREFIX

    @pytest.mark.skipif(
        not pathlib.Path("/proc/stat").exists(),
        reason="the resource sampler reads /proc/stat, which only exists on Linux",
    )
    def test_oar_multinode_job_traces_the_local_node(self, tmp_path):
        """
        Regression test: an OAR multi-node job used to fall into the single-node
        branch because SLURM_JOB_ID was unset. The trace must now be named after
        the OAR job id, proving the scheduler was recognised, and the local node
        must still be sampled even when remote nodes are unreachable.
        """
        prefix = self._sampler_files(tmp_path)

        nodefile = tmp_path / "nodefile"
        hostname = subprocess.run(
            ["hostname"], capture_output=True, text=True
        ).stdout.strip()
        # The local node is listed by FQDN while `hostname` may return the short
        # name, so the launcher has to compare short names to recognise itself.
        nodefile.write_text(f"{hostname}.fake.invalid\niops-unreachable-node-xyz\n")

        job = _write_script(tmp_path / "job.sh", f'''#!/bin/bash
export OAR_JOB_ID=987654
export OAR_NODEFILE="{nodefile}"
source "{tmp_path}/handler.sh"
source "{tmp_path}/launcher.sh"
source "{tmp_path}/sampler.sh"
sleep 0.6
''')

        result = subprocess.run(
            ["bash", str(job)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
        assert result.returncode == 0

        traces = list(tmp_path.glob(f"{prefix}*_987654.csv"))
        assert traces, (
            "Local trace must be named after the OAR job id; "
            f"found {[p.name for p in tmp_path.glob(prefix + '*')]}"
        )
        assert len(traces[0].read_text().strip().split("\n")) > 1, "trace has no samples"

    def test_slurm_multinode_uses_srun(self, tmp_path):
        """Under SLURM the launcher must still delegate to a single srun call."""
        self._sampler_files(tmp_path)

        bindir = tmp_path / "bin"
        bindir.mkdir()
        argv_log = tmp_path / "srun_argv"
        _write_script(bindir / "srun", f'#!/bin/bash\necho "$@" > "{argv_log}"\n')

        job = _write_script(tmp_path / "job.sh", f'''#!/bin/bash
export PATH="{bindir}:$PATH"
export SLURM_JOB_ID=4242
export SLURM_NNODES=4
source "{tmp_path}/handler.sh"
source "{tmp_path}/launcher.sh"
source "{tmp_path}/sampler.sh"
sleep 0.4
''')

        subprocess.run(
            ["bash", str(job)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )

        assert argv_log.exists(), "srun was not invoked for a SLURM multi-node job"
        argv = argv_log.read_text()
        assert "--overlap" in argv
        assert "--nodes=4" in argv
        assert "--ntasks-per-node=1" in argv

    def test_remote_helper_inherits_the_attempt_id(self, tmp_path):
        """
        Remote samplers must reuse the head node's attempt id, otherwise they
        compute a different sentinel path and exit immediately.
        """
        self._sampler_files(tmp_path)

        bindir = tmp_path / "bin"
        bindir.mkdir()
        cmd_log = tmp_path / "rsh_cmd"
        # Stand in for ssh: record the remote command instead of running it
        _write_script(bindir / "ssh", f'#!/bin/bash\necho "${{@: -1}}" > "{cmd_log}"\n')

        nodefile = tmp_path / "nodefile"
        nodefile.write_text("iops-remote-node-a\n")

        job = _write_script(tmp_path / "job.sh", f'''#!/bin/bash
export PATH="{bindir}:$PATH"
export PBS_NODEFILE="{nodefile}"
export PBS_JOBID=555
source "{tmp_path}/handler.sh"
source "{tmp_path}/launcher.sh"
source "{tmp_path}/sampler.sh"
sleep 0.4
''')

        subprocess.run(
            ["bash", str(job)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )

        assert cmd_log.exists(), "no remote shell invocation was recorded"
        remote_cmd = cmd_log.read_text()
        assert "IOPS_ATTEMPT_ID='555'" in remote_cmd
        assert "sampler.sh" in remote_cmd

    def test_sampler_still_works_without_the_launcher(self, tmp_path):
        """Sourcing a sampler on its own must degrade to local sampling."""
        prefix = self._sampler_files(tmp_path)

        job = _write_script(tmp_path / "job.sh", f'''#!/bin/bash
source "{tmp_path}/handler.sh"
source "{tmp_path}/sampler.sh"
sleep 0.4
''')

        result = subprocess.run(
            ["bash", str(job)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
        assert result.returncode == 0

        traces = list(tmp_path.glob(f"{prefix}*.csv"))
        assert traces, "sampler must still trace the local node without a launcher"


# ============================================================================ #
# Injection
# ============================================================================ #

class TestNodeLauncherInjection:
    """Tests for launcher injection into generated scripts."""

    def _planner(self, sample_config_dict, tmp_path, probes):
        sample_config_dict["benchmark"]["probes"] = probes
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        from iops.execution.planner import BasePlanner
        return BasePlanner.build(load_config(config_file))

    def test_launcher_written_when_resource_sampling_enabled(self, sample_config_dict, tmp_path):
        from iops.execution.planner import NODE_LAUNCHER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {"resource_sampling": True, "system_snapshot": False},
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script = planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)

        launcher_file = exec_dir / NODE_LAUNCHER_FILENAME
        assert launcher_file.exists()
        assert f'source "{launcher_file}"' in script

    def test_launcher_written_when_gpu_sampling_enabled(self, sample_config_dict, tmp_path):
        from iops.execution.planner import NODE_LAUNCHER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {"gpu_sampling": True, "system_snapshot": False},
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)
        assert (exec_dir / NODE_LAUNCHER_FILENAME).exists()

    def test_launcher_skipped_when_no_sampler_enabled(self, sample_config_dict, tmp_path):
        from iops.execution.planner import NODE_LAUNCHER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {"resource_sampling": False, "gpu_sampling": False, "system_snapshot": True},
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)
        assert not (exec_dir / NODE_LAUNCHER_FILENAME).exists()

    def test_launcher_sourced_before_sampler(self, sample_config_dict, tmp_path):
        """The sampler calls into the launcher, so ordering matters."""
        from iops.execution.planner import NODE_LAUNCHER_FILENAME, RUNTIME_SAMPLER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {"resource_sampling": True, "system_snapshot": False},
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script = planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)

        launcher_pos = script.index(NODE_LAUNCHER_FILENAME)
        sampler_pos = script.index(RUNTIME_SAMPLER_FILENAME)
        assert launcher_pos < sampler_pos
