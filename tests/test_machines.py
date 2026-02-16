"""Tests for machine-specific config overrides."""

import pytest
import yaml
import logging
from pathlib import Path

from iops.config.merge import deep_merge, _is_named_object_list, _merge_named_lists
from iops.config.loader import (
    _apply_machine_override,
    _resolve_machine_name,
    load_generic_config,
    validate_yaml_config,
)
from iops.config.models import ConfigValidationError


# =========================================================================
# deep_merge unit tests
# =========================================================================

class TestDeepMerge:
    def test_simple_dict_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_dict_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}

    def test_deeply_nested_merge(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"d": 99, "e": 100}}}
        result = deep_merge(base, override)
        assert result == {"a": {"b": {"c": 1, "d": 99, "e": 100}}}

    def test_scalar_list_replace(self):
        base = {"values": [1, 2, 3]}
        override = {"values": [10, 20]}
        result = deep_merge(base, override)
        assert result == {"values": [10, 20]}

    def test_string_list_replace(self):
        base = {"tags": ["a", "b", "c"]}
        override = {"tags": ["x"]}
        result = deep_merge(base, override)
        assert result == {"tags": ["x"]}

    def test_named_list_merge_by_name(self):
        base = [{"name": "foo", "value": 1}, {"name": "bar", "value": 2}]
        override = [{"name": "foo", "value": 99}]
        result = _merge_named_lists(base, override)
        assert len(result) == 2
        assert result[0] == {"name": "foo", "value": 99}
        assert result[1] == {"name": "bar", "value": 2}

    def test_named_list_append_new(self):
        base = [{"name": "foo", "value": 1}]
        override = [{"name": "bar", "value": 2}]
        result = _merge_named_lists(base, override)
        assert len(result) == 2
        assert result[0] == {"name": "foo", "value": 1}
        assert result[1] == {"name": "bar", "value": 2}

    def test_named_list_deep_merge_items(self):
        base = [{"name": "s1", "template": "base", "parser": {"file": "a.txt"}}]
        override = [{"name": "s1", "parser": {"file": "b.txt", "extra": True}}]
        result = _merge_named_lists(base, override)
        assert len(result) == 1
        assert result[0]["name"] == "s1"
        assert result[0]["template"] == "base"
        assert result[0]["parser"] == {"file": "b.txt", "extra": True}

    def test_named_list_via_deep_merge(self):
        base = {"scripts": [{"name": "s1", "value": 1}]}
        override = {"scripts": [{"name": "s1", "value": 99}, {"name": "s2", "value": 2}]}
        result = deep_merge(base, override)
        assert len(result["scripts"]) == 2
        assert result["scripts"][0] == {"name": "s1", "value": 99}
        assert result["scripts"][1] == {"name": "s2", "value": 2}

    def test_empty_override(self):
        base = {"a": 1, "b": {"c": 2}}
        result = deep_merge(base, {})
        assert result == base
        assert result is not base  # new object

    def test_empty_base(self):
        override = {"a": 1, "b": {"c": 2}}
        result = deep_merge({}, override)
        assert result == override
        assert result is not override

    def test_no_mutation_of_inputs(self):
        base = {"a": {"x": [1, 2]}, "b": 3}
        override = {"a": {"x": [10], "y": 4}}
        base_copy = {"a": {"x": [1, 2]}, "b": 3}
        override_copy = {"a": {"x": [10], "y": 4}}
        deep_merge(base, override)
        assert base == base_copy
        assert override == override_copy

    def test_type_mismatch_override_wins(self):
        base = {"a": [1, 2, 3]}
        override = {"a": "replaced"}
        result = deep_merge(base, override)
        assert result == {"a": "replaced"}

    def test_type_mismatch_dict_to_scalar(self):
        base = {"a": {"nested": True}}
        override = {"a": 42}
        result = deep_merge(base, override)
        assert result == {"a": 42}

    def test_empty_list_replaces(self):
        base = {"items": [1, 2, 3]}
        override = {"items": []}
        result = deep_merge(base, override)
        assert result == {"items": []}

    def test_none_value_override(self):
        base = {"a": 1}
        override = {"a": None}
        result = deep_merge(base, override)
        assert result == {"a": None}

    def test_override_adds_new_keys(self):
        base = {"a": 1}
        override = {"b": 2}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 2}


class TestIsNamedObjectList:
    def test_named_list(self):
        assert _is_named_object_list([{"name": "a"}, {"name": "b"}]) is True

    def test_empty_list(self):
        assert _is_named_object_list([]) is False

    def test_scalar_list(self):
        assert _is_named_object_list([1, 2, 3]) is False

    def test_dict_without_name(self):
        assert _is_named_object_list([{"key": "val"}]) is False

    def test_mixed_list(self):
        assert _is_named_object_list([{"name": "a"}, {"key": "val"}]) is False

    def test_mixed_types(self):
        assert _is_named_object_list([{"name": "a"}, "string"]) is False


# =========================================================================
# _apply_machine_override tests
# =========================================================================

class TestApplyMachineOverride:
    def _base_config(self, tmp_path):
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        return {
            "benchmark": {
                "name": "Test",
                "workdir": str(workdir),
                "executor": "local",
            },
            "vars": {
                "nodes": {"type": "int", "sweep": {"mode": "list", "values": [1, 2]}},
                "scratch": {"type": "str", "expr": "/default/scratch"},
            },
            "command": {"template": "echo {{ nodes }}"},
            "scripts": [
                {
                    "name": "bench",
                    "script_template": "#!/bin/bash\necho {{ nodes }}",
                    "parser": {
                        "file": "{{ execution_dir }}/out.txt",
                        "metrics": [{"name": "result"}],
                        "parser_script": "def parse(file_path):\n    return {'result': 1.0}",
                    },
                }
            ],
            "output": {"sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}},
        }

    def test_vars_override(self, tmp_path):
        data = self._base_config(tmp_path)
        data["machines"] = {
            "cluster_a": {
                "vars": {"scratch": {"type": "str", "expr": "/lustre/scratch"}},
            }
        }
        result = _apply_machine_override(data, "cluster_a")
        assert result["vars"]["scratch"]["expr"] == "/lustre/scratch"
        assert result["vars"]["nodes"]["type"] == "int"  # preserved from base
        assert "machines" not in result

    def test_vars_add_new(self, tmp_path):
        data = self._base_config(tmp_path)
        data["machines"] = {
            "cluster_a": {
                "vars": {"new_var": {"type": "str", "expr": "hello"}},
            }
        }
        result = _apply_machine_override(data, "cluster_a")
        assert "new_var" in result["vars"]
        assert result["vars"]["new_var"]["expr"] == "hello"

    def test_scripts_merge_by_name(self, tmp_path):
        data = self._base_config(tmp_path)
        data["machines"] = {
            "cluster_a": {
                "scripts": [
                    {"name": "bench", "script_template": "#!/bin/bash\ncustom script"},
                ]
            }
        }
        result = _apply_machine_override(data, "cluster_a")
        assert len(result["scripts"]) == 1
        assert result["scripts"][0]["name"] == "bench"
        assert "custom script" in result["scripts"][0]["script_template"]
        # Parser should be preserved from base (deep merge)
        assert "parser" in result["scripts"][0]

    def test_scripts_append_new(self, tmp_path):
        data = self._base_config(tmp_path)
        data["machines"] = {
            "cluster_a": {
                "scripts": [
                    {"name": "new_script", "script_template": "#!/bin/bash\nnew"},
                ]
            }
        }
        result = _apply_machine_override(data, "cluster_a")
        assert len(result["scripts"]) == 2
        names = [s["name"] for s in result["scripts"]]
        assert "bench" in names
        assert "new_script" in names

    def test_benchmark_deep_merge(self, tmp_path):
        data = self._base_config(tmp_path)
        data["benchmark"]["repetitions"] = 3
        data["machines"] = {
            "cluster_a": {
                "benchmark": {"executor": "slurm"},
            }
        }
        result = _apply_machine_override(data, "cluster_a")
        assert result["benchmark"]["executor"] == "slurm"
        assert result["benchmark"]["name"] == "Test"  # preserved
        assert result["benchmark"]["repetitions"] == 3  # preserved

    def test_output_path_override(self, tmp_path):
        data = self._base_config(tmp_path)
        data["machines"] = {
            "cluster_a": {
                "output": {"sink": {"path": "/custom/results.csv"}},
            }
        }
        result = _apply_machine_override(data, "cluster_a")
        assert result["output"]["sink"]["path"] == "/custom/results.csv"
        assert result["output"]["sink"]["type"] == "csv"  # preserved

    def test_sweep_to_expr_clears_sweep(self, tmp_path):
        """When override provides expr for a swept var, sweep is removed."""
        data = self._base_config(tmp_path)
        # Base has nodes with sweep
        assert "sweep" in data["vars"]["nodes"]
        data["machines"] = {
            "cluster_a": {
                "vars": {"nodes": {"type": "int", "expr": "1"}},
            }
        }
        result = _apply_machine_override(data, "cluster_a")
        assert result["vars"]["nodes"]["expr"] == "1"
        assert "sweep" not in result["vars"]["nodes"]

    def test_expr_to_sweep_clears_expr(self, tmp_path):
        """When override provides sweep for a derived var, expr is removed."""
        data = self._base_config(tmp_path)
        # Base has scratch with expr
        assert "expr" in data["vars"]["scratch"]
        data["machines"] = {
            "cluster_a": {
                "vars": {"scratch": {"type": "str", "sweep": {"mode": "list", "values": ["/a", "/b"]}}},
            }
        }
        result = _apply_machine_override(data, "cluster_a")
        assert result["vars"]["scratch"]["sweep"]["values"] == ["/a", "/b"]
        assert "expr" not in result["vars"]["scratch"]

    def test_unknown_machine_error(self, tmp_path):
        data = self._base_config(tmp_path)
        data["machines"] = {"cluster_a": {"benchmark": {"executor": "local"}}}
        with pytest.raises(ConfigValidationError, match="Unknown machine 'cluster_b'"):
            _apply_machine_override(data, "cluster_b")

    def test_missing_machines_section_error(self, tmp_path):
        data = self._base_config(tmp_path)
        with pytest.raises(ConfigValidationError, match="no 'machines' section"):
            _apply_machine_override(data, "cluster_a")

    def test_invalid_override_keys_error(self, tmp_path):
        data = self._base_config(tmp_path)
        data["machines"] = {
            "cluster_a": {"invalid_section": {"foo": "bar"}},
        }
        with pytest.raises(ConfigValidationError, match="invalid override keys"):
            _apply_machine_override(data, "cluster_a")

    def test_machine_value_not_dict_error(self, tmp_path):
        data = self._base_config(tmp_path)
        data["machines"] = {"cluster_a": "not a dict"}
        with pytest.raises(ConfigValidationError, match="must be a dictionary"):
            _apply_machine_override(data, "cluster_a")


# =========================================================================
# _resolve_machine_name tests
# =========================================================================

class TestResolveMachineName:
    def test_cli_arg_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("IOPS_MACHINE", "from_env")
        assert _resolve_machine_name("from_cli") == "from_cli"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("IOPS_MACHINE", "from_env")
        assert _resolve_machine_name(None) == "from_env"

    def test_none_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("IOPS_MACHINE", raising=False)
        assert _resolve_machine_name(None) is None


# =========================================================================
# End-to-end tests
# =========================================================================

class TestMachineEndToEnd:
    def _write_config(self, tmp_path, config_dict):
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_dict, f)
        return config_file

    def _base_config_dict(self, tmp_path):
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        return {
            "benchmark": {
                "name": "Test Benchmark",
                "workdir": str(workdir),
                "executor": "local",
            },
            "vars": {
                "nodes": {"type": "int", "sweep": {"mode": "list", "values": [1, 2]}},
                "ppn": {"type": "int", "expr": "4"},
            },
            "command": {"template": "echo '{{ nodes }}'"},
            "scripts": [
                {
                    "name": "test_script",
                    "script_template": "#!/bin/bash\necho '{{ nodes }}'",
                    "parser": {
                        "file": "{{ execution_dir }}/output.txt",
                        "metrics": [{"name": "result"}],
                        "parser_script": "def parse(file_path):\n    return {'result': 1.0}",
                    },
                }
            ],
            "output": {"sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}},
        }

    def test_load_generic_config_with_machine(self, tmp_path):
        cfg_dict = self._base_config_dict(tmp_path)
        cfg_dict["machines"] = {
            "cluster_a": {
                "vars": {"ppn": {"type": "int", "expr": "8"}},
            }
        }
        config_file = self._write_config(tmp_path, cfg_dict)
        logger = logging.getLogger("test")

        cfg = load_generic_config(config_file, logger, machine="cluster_a")
        assert cfg.vars["ppn"].expr == "8"
        assert cfg.vars["nodes"].sweep is not None  # preserved

    def test_load_generic_config_without_machine(self, tmp_path):
        cfg_dict = self._base_config_dict(tmp_path)
        cfg_dict["machines"] = {
            "cluster_a": {
                "vars": {"ppn": {"type": "int", "expr": "8"}},
            }
        }
        config_file = self._write_config(tmp_path, cfg_dict)
        logger = logging.getLogger("test")

        cfg = load_generic_config(config_file, logger)
        assert cfg.vars["ppn"].expr == "4"  # base value, not overridden

    def test_validate_yaml_config_with_machine(self, tmp_path):
        cfg_dict = self._base_config_dict(tmp_path)
        cfg_dict["machines"] = {
            "cluster_a": {
                "vars": {"ppn": {"type": "int", "expr": "8"}},
            }
        }
        config_file = self._write_config(tmp_path, cfg_dict)
        errors = validate_yaml_config(config_file, machine="cluster_a")
        assert errors == []

    def test_validate_yaml_config_unknown_machine(self, tmp_path):
        cfg_dict = self._base_config_dict(tmp_path)
        cfg_dict["machines"] = {
            "cluster_a": {
                "vars": {"ppn": {"type": "int", "expr": "8"}},
            }
        }
        config_file = self._write_config(tmp_path, cfg_dict)
        errors = validate_yaml_config(config_file, machine="nonexistent")
        assert len(errors) == 1
        assert "Unknown machine" in errors[0]

    def test_machines_section_validated_without_flag(self, tmp_path):
        """machines section is structurally validated even without --machine."""
        cfg_dict = self._base_config_dict(tmp_path)
        cfg_dict["machines"] = {"cluster_a": "not a dict"}
        config_file = self._write_config(tmp_path, cfg_dict)
        errors = validate_yaml_config(config_file)
        assert len(errors) > 0
        assert "must be a dictionary" in errors[0]

    def test_machines_invalid_keys_validated_without_flag(self, tmp_path):
        cfg_dict = self._base_config_dict(tmp_path)
        cfg_dict["machines"] = {
            "cluster_a": {"invalid_section": {"x": 1}},
        }
        config_file = self._write_config(tmp_path, cfg_dict)
        errors = validate_yaml_config(config_file)
        assert len(errors) > 0
        assert "invalid override keys" in errors[0]

    def test_env_var_machine_selection(self, tmp_path, monkeypatch):
        cfg_dict = self._base_config_dict(tmp_path)
        cfg_dict["machines"] = {
            "cluster_b": {
                "vars": {"ppn": {"type": "int", "expr": "16"}},
            }
        }
        config_file = self._write_config(tmp_path, cfg_dict)
        logger = logging.getLogger("test")

        monkeypatch.setenv("IOPS_MACHINE", "cluster_b")
        cfg = load_generic_config(config_file, logger)
        assert cfg.vars["ppn"].expr == "16"


# =========================================================================
# Jerome's example as integration test
# =========================================================================

class TestJeromeExample:
    def _jerome_config(self, tmp_path):
        workdir = tmp_path / "results"
        workdir.mkdir(parents=True, exist_ok=True)
        return {
            "benchmark": {
                "name": "IOR Benchmark",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
            },
            "vars": {
                "nodes": {"type": "int", "sweep": {"mode": "list", "values": [1, 2, 4, 8]}},
                "scratch": {"type": "str", "expr": "/default/scratch"},
                "transfer_size": {"type": "str", "expr": "1m"},
            },
            "command": {"template": "ior -w -t {{ transfer_size }} -o {{ scratch }}/testfile"},
            "scripts": [
                {
                    "name": "benchmark",
                    "script_template": "#!/bin/bash\nmodule load mpi\nmpirun {{ command.template }}",
                    "parser": {
                        "file": "{{ execution_dir }}/output.txt",
                        "metrics": [{"name": "bandwidth"}],
                        "parser_script": "def parse(file_path):\n    return {'bandwidth': 1.0}",
                    },
                }
            ],
            "output": {"sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}},
            "machines": {
                "cluster_a": {
                    "benchmark": {
                        "slurm_options": {
                            "commands": {"submit": "ccc_msub", "cancel": "ccc_mdel {job_id}"},
                        }
                    },
                    "output": {"sink": {"path": "/path/on/irene/results_cluster_a.csv"}},
                    "vars": {
                        "scratch": {"type": "str", "expr": "/lustre/scratch"},
                        "mpi_module": {"type": "str", "expr": "openmpi/4.1"},
                    },
                    "scripts": [
                        {
                            "name": "benchmark",
                            "script_template": "#!/bin/bash\nmodule load {{ mpi_module }}\nmpirun {{ command.template }}",
                            "parser": {
                                "metrics": [{"name": "my_extra_metric"}],
                                "parser_script": "def parse(file_path):\n    return {'bandwidth': 1.0, 'my_extra_metric': 2.0}",
                            },
                        }
                    ],
                },
                "cluster_b": {
                    "output": {"sink": {"path": "/some/other/path/results_cluster_b.csv"}},
                },
            },
        }

    def test_cluster_a_overrides(self, tmp_path):
        data = self._jerome_config(tmp_path)
        result = _apply_machine_override(data, "cluster_a")

        # Vars: scratch overridden, mpi_module added, nodes+transfer_size preserved
        assert result["vars"]["scratch"]["expr"] == "/lustre/scratch"
        assert result["vars"]["mpi_module"]["expr"] == "openmpi/4.1"
        assert result["vars"]["nodes"]["sweep"]["values"] == [1, 2, 4, 8]
        assert result["vars"]["transfer_size"]["expr"] == "1m"

        # Output path overridden
        assert result["output"]["sink"]["path"] == "/path/on/irene/results_cluster_a.csv"
        assert result["output"]["sink"]["type"] == "csv"  # preserved

        # Script merged by name: template overridden, parser deep-merged
        assert len(result["scripts"]) == 1
        assert result["scripts"][0]["name"] == "benchmark"
        assert "mpi_module" in result["scripts"][0]["script_template"]

        # Parser deep-merged: metrics from override merged with base
        parser = result["scripts"][0]["parser"]
        assert parser["parser_script"] is not None
        # file preserved from base
        assert parser["file"] == "{{ execution_dir }}/output.txt"
        # metrics: base had [bandwidth], override has [my_extra_metric]
        # Since metrics is a named-object list, they merge by name
        metric_names = [m["name"] for m in parser["metrics"]]
        assert "bandwidth" in metric_names
        assert "my_extra_metric" in metric_names

        # Benchmark: slurm_options added
        assert result["benchmark"]["slurm_options"]["commands"]["submit"] == "ccc_msub"
        assert result["benchmark"]["name"] == "IOR Benchmark"  # preserved

    def test_cluster_b_overrides(self, tmp_path):
        data = self._jerome_config(tmp_path)
        result = _apply_machine_override(data, "cluster_b")

        # Only output path changed
        assert result["output"]["sink"]["path"] == "/some/other/path/results_cluster_b.csv"

        # Everything else preserved
        assert result["vars"]["scratch"]["expr"] == "/default/scratch"
        assert "mpi_module" not in result["vars"]
        assert len(result["scripts"]) == 1
        assert result["scripts"][0]["name"] == "benchmark"
        assert result["benchmark"]["name"] == "IOR Benchmark"

    def test_no_machine_base_config_works(self, tmp_path):
        """Config with machines section loads fine without --machine."""
        data = self._jerome_config(tmp_path)
        config_file = tmp_path / "jerome.yaml"
        with open(config_file, "w") as f:
            yaml.dump(data, f)

        logger = logging.getLogger("test")
        cfg = load_generic_config(config_file, logger)
        assert cfg.benchmark.name == "IOR Benchmark"
        assert cfg.vars["scratch"].expr == "/default/scratch"
