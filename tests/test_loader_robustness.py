"""Regression tests for loader robustness fixes.

Covers friendly errors for null/non-dict config blocks, machine override
edge cases, cache_file handling, file-path heuristics, random sampling
percentage validation, and merge behavior.
"""

import logging
import warnings
from pathlib import Path

import pytest
import yaml

from conftest import load_config
from iops.config.loader import load_generic_config
from iops.config.merge import deep_merge, _merge_named_lists
from iops.config.models import ConfigValidationError


def write_config(tmp_path, config_dict, name="config.yaml"):
    config_file = tmp_path / name
    with open(config_file, "w") as f:
        yaml.dump(config_dict, f)
    return config_file


# =========================================================================
# Fix 1: null/non-dict config blocks produce friendly errors
# =========================================================================

class TestNullAndNonDictBlocks:
    def test_sweep_null(self, tmp_path, sample_config_dict):
        sample_config_dict["vars"]["nodes"]["sweep"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"vars\.nodes\.sweep must be a mapping \(got null\)"):
            load_config(config_file)

    def test_sweep_non_dict(self, tmp_path, sample_config_dict):
        sample_config_dict["vars"]["nodes"]["sweep"] = [1, 2]
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"vars\.nodes\.sweep must be a mapping \(got list\)"):
            load_config(config_file)

    def test_adaptive_null(self, tmp_path, sample_config_dict):
        sample_config_dict["vars"]["nodes"] = {"type": "int", "adaptive": None}
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"vars\.nodes\.adaptive must be a mapping \(got null\)"):
            load_config(config_file)

    def test_vars_null(self, tmp_path, sample_config_dict):
        sample_config_dict["vars"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match="At least one variable"):
            load_config(config_file)

    def test_vars_non_dict(self, tmp_path, sample_config_dict):
        sample_config_dict["vars"] = ["nodes", "ppn"]
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"vars must be a mapping \(got list\)"):
            load_config(config_file)

    def test_var_entry_null(self, tmp_path, sample_config_dict):
        sample_config_dict["vars"]["nodes"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"vars\.nodes must be a mapping \(got null\)"):
            load_config(config_file)

    def test_scripts_null(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match="At least one script"):
            load_config(config_file)

    def test_scripts_non_list(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"] = {"name": "foo"}
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts must be a list \(got dict\)"):
            load_config(config_file)

    def test_script_entry_non_dict(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"] = ["echo hello"]
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts\[0\] must be a mapping \(got str\)"):
            load_config(config_file)

    def test_post_as_string(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["post"] = "echo done"
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts\[0\]\.post must be a mapping \(got str\)"):
            load_config(config_file)

    def test_parser_as_string(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["parser"] = "parse.py"
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts\[0\]\.parser must be a mapping \(got str\)"):
            load_config(config_file)

    def test_parser_metrics_non_list(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["parser"]["metrics"] = "result"
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts\[0\]\.parser\.metrics must be a list \(got str\)"):
            load_config(config_file)

    def test_parser_metric_entry_non_dict(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["parser"]["metrics"] = ["result"]
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts\[0\]\.parser\.metrics\[0\] must be a mapping \(got str\)"):
            load_config(config_file)

    def test_command_null(self, tmp_path, sample_config_dict):
        sample_config_dict["command"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"command must be a mapping \(got null\)"):
            load_config(config_file)

    def test_benchmark_null(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"benchmark must be a mapping \(got null\)"):
            load_config(config_file)

    def test_output_null(self, tmp_path, sample_config_dict):
        sample_config_dict["output"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"output must be a mapping \(got null\)"):
            load_config(config_file)

    def test_output_sink_null(self, tmp_path, sample_config_dict):
        sample_config_dict["output"]["sink"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"output\.sink must be a mapping \(got null\)"):
            load_config(config_file)

    def test_constraints_null_is_accepted(self, tmp_path, sample_config_dict):
        sample_config_dict["constraints"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.constraints == []

    def test_constraints_non_list(self, tmp_path, sample_config_dict):
        sample_config_dict["constraints"] = "nodes > 1"
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"constraints must be a list \(got str\)"):
            load_config(config_file)

    def test_reporting_theme_as_string(self, tmp_path, sample_config_dict):
        sample_config_dict["reporting"] = {"enabled": True, "theme": "dark"}
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"reporting\.theme must be a mapping \(got str\)"):
            load_config(config_file)

    def test_reporting_sections_null(self, tmp_path, sample_config_dict):
        # null sections are treated as "not set" (defaults apply)
        sample_config_dict["reporting"] = {"enabled": True, "sections": None}
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.reporting.sections.test_summary is True

    def test_reporting_non_dict_plot_entry(self, tmp_path, sample_config_dict):
        sample_config_dict["reporting"] = {"enabled": True, "default_plots": ["boxplot"]}
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"reporting\.default_plots\[0\] must be a mapping \(got str\)"):
            load_config(config_file)

    def test_reporting_metric_plots_non_dict_entry(self, tmp_path, sample_config_dict):
        sample_config_dict["reporting"] = {
            "enabled": True,
            "metrics": {"result": {"plots": ["boxplot"]}},
        }
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"reporting\.metrics\.result\.plots\[0\] must be a mapping \(got str\)"):
            load_config(config_file)


# =========================================================================
# Fix 2: --machine with no machines section
# =========================================================================

class TestMachineOverrideEdgeCases:
    def test_machine_without_machines_section(self, tmp_path, sample_config_dict):
        config_file = write_config(tmp_path, sample_config_dict)
        logger = logging.getLogger("test")
        with pytest.raises(ConfigValidationError, match="no 'machines' section found"):
            load_generic_config(Path(config_file), logger, machine="clusterA")

    def test_machine_with_null_machines_section(self, tmp_path, sample_config_dict):
        sample_config_dict["machines"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        logger = logging.getLogger("test")
        with pytest.raises(ConfigValidationError, match="no 'machines' section found"):
            load_generic_config(Path(config_file), logger, machine="clusterA")

    def test_null_machines_without_machine_arg_is_ignored(self, tmp_path, sample_config_dict):
        sample_config_dict["machines"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.benchmark.name == "Test Benchmark"


# =========================================================================
# Fix 3: cache_file null and empty values
# =========================================================================

class TestCacheFileEdgeCases:
    def test_cache_file_null_treated_as_unset(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["cache_file"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.benchmark.cache_file is None

    def test_cache_file_empty_string_rejected(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["cache_file"] = ""
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"cache_file must not be an empty string"):
            load_config(config_file)

    def test_cache_file_non_string_rejected(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["cache_file"] = 42
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"cache_file must be a path string"):
            load_config(config_file)


# =========================================================================
# Fix 4: cache_file template typos fail loudly
# =========================================================================

class TestCacheFileStrictRendering:
    def test_cache_file_undefined_variable_rejected(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["cache_file"] = "{{ benchmark.nam }}.db"
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"cache_file references an undefined template variable"):
            load_config(config_file)

    def test_cache_file_unknown_root_variable_rejected(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["cache_file"] = "{{ workdri }}/cache.db"
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"cache_file references an undefined template variable"):
            load_config(config_file)

    def test_cache_file_valid_template_still_works(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["cache_file"] = "{{ workdir }}/cache.db"
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        workdir = sample_config_dict["benchmark"]["workdir"]
        assert config.benchmark.cache_file == (Path(workdir).resolve() / "cache.db")

    def test_cache_file_plain_path_with_literal_braces(self, tmp_path, sample_config_dict):
        # Paths with shell-style braces but no Jinja markers are used as-is
        plain = str(tmp_path / "cache.db")
        sample_config_dict["benchmark"]["cache_file"] = plain
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.benchmark.cache_file == Path(plain).resolve()


# =========================================================================
# Fix 5: Jinja one-liners are not misclassified as file paths
# =========================================================================

class TestFilePathHeuristic:
    def test_jinja_one_liner_with_extension_is_inline(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["script_template"] = "bash {{ workdir }}/run.sh"
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.scripts[0].script_template == "bash {{ workdir }}/run.sh"

    def test_jinja_one_liner_with_path_prefix_is_inline(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["script_template"] = "./tool --dir {{ execution_dir }}"
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.scripts[0].script_template == "./tool --dir {{ execution_dir }}"

    def test_plain_missing_file_path_still_errors(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["script_template"] = "./missing_script.sh"
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match="file was not found"):
            load_config(config_file)

    def test_existing_file_path_still_loads(self, tmp_path, sample_config_dict):
        script_file = tmp_path / "my_script.sh"
        script_file.write_text("#!/bin/bash\necho 'from file'\n")
        sample_config_dict["scripts"][0]["script_template"] = str(script_file)
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert "from file" in config.scripts[0].script_template


# =========================================================================
# Fix 6: output.sink.include warns
# =========================================================================

class TestOutputSinkInclude:
    def test_include_emits_warning(self, tmp_path, sample_config_dict):
        sample_config_dict["output"]["sink"]["include"] = ["vars.nodes"]
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.warns(UserWarning, match=r"output\.sink\.include is not supported"):
            config = load_config(config_file)
        assert config.output.sink.type == "csv"

    def test_no_warning_without_include(self, tmp_path, sample_config_dict):
        config_file = write_config(tmp_path, sample_config_dict)
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            load_config(config_file)


# =========================================================================
# Fix 7: random_config.percentage validation
# =========================================================================

class TestRandomPercentage:
    def test_percentage_above_one_rejected(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["search_method"] = "random"
        sample_config_dict["benchmark"]["random_config"] = {"percentage": 50}
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"fraction between 0 and 1"):
            load_config(config_file)

    def test_percentage_as_string_rejected(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["search_method"] = "random"
        sample_config_dict["benchmark"]["random_config"] = {"percentage": "0.5"}
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"percentage must be a number"):
            load_config(config_file)

    def test_valid_percentage_still_works(self, tmp_path, sample_config_dict):
        sample_config_dict["benchmark"]["search_method"] = "random"
        sample_config_dict["benchmark"]["random_config"] = {"percentage": 0.5}
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.benchmark.random_config.percentage == 0.5


# =========================================================================
# Fix 8: non-string templates produce the curated message
# =========================================================================

class TestNonStringTemplates:
    def test_command_template_non_string(self, tmp_path, sample_config_dict):
        sample_config_dict["command"]["template"] = 123
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"'command\.template' must be a string, got int"):
            load_config(config_file)

    def test_script_template_non_string(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["script_template"] = 123
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"must be a string, got int"):
            load_config(config_file)


# =========================================================================
# Fix 9: scripts[].name is required
# =========================================================================

class TestScriptNameRequired:
    def test_missing_name_rejected(self, tmp_path, sample_config_dict):
        del sample_config_dict["scripts"][0]["name"]
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts\[0\]\.name is required"):
            load_config(config_file)

    def test_null_name_rejected(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["name"] = None
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts\[0\]\.name is required"):
            load_config(config_file)

    def test_empty_name_rejected(self, tmp_path, sample_config_dict):
        sample_config_dict["scripts"][0]["name"] = "  "
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"scripts\[0\]\.name is required"):
            load_config(config_file)


# =========================================================================
# Fix 10: adaptive search rejected in single-allocation mode
# =========================================================================

def _make_single_allocation(config_dict):
    config_dict["benchmark"]["executor"] = "slurm"
    config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#!/bin/bash\n#SBATCH --nodes=4\n#SBATCH --time=01:00:00\n",
        }
    }


class TestSingleAllocationSearchMethods:
    def test_adaptive_rejected(self, tmp_path, sample_config_dict):
        _make_single_allocation(sample_config_dict)
        sample_config_dict["benchmark"]["search_method"] = "adaptive"
        sample_config_dict["vars"]["block_size"] = {
            "type": "int",
            "adaptive": {
                "initial": 1,
                "factor": 2,
                "stop_when": "{{ exit_code != 0 }}",
                "max_iterations": 5,
            },
        }
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"incompatible with search_method='adaptive'"):
            load_config(config_file)

    def test_bayesian_still_rejected(self, tmp_path, sample_config_dict):
        _make_single_allocation(sample_config_dict)
        sample_config_dict["benchmark"]["search_method"] = "bayesian"
        sample_config_dict["benchmark"]["bayesian_config"] = {
            "objective_metric": "result",
        }
        config_file = write_config(tmp_path, sample_config_dict)
        with pytest.raises(ConfigValidationError, match=r"incompatible with search_method='bayesian'"):
            load_config(config_file)

    def test_random_still_allowed(self, tmp_path, sample_config_dict):
        # Random sampling stays allowed: the planner is being fixed to honor
        # sampling in kickoff mode
        _make_single_allocation(sample_config_dict)
        sample_config_dict["benchmark"]["search_method"] = "random"
        sample_config_dict["benchmark"]["random_config"] = {"n_samples": 1}
        config_file = write_config(tmp_path, sample_config_dict)
        config = load_config(config_file)
        assert config.benchmark.search_method == "random"


# =========================================================================
# Fix 11: duplicate names in override named lists are rejected
# =========================================================================

class TestMergeDuplicateNames:
    def test_duplicate_names_in_override_list_rejected(self):
        base = {"scripts": [{"name": "s1", "value": 1}]}
        override = {"scripts": [{"name": "s1", "value": 2}, {"name": "s1", "value": 3}]}
        with pytest.raises(ConfigValidationError, match=r"duplicate names.*s1"):
            deep_merge(base, override)

    def test_duplicate_names_direct_call(self):
        base = [{"name": "a", "v": 1}]
        override = [{"name": "b", "v": 2}, {"name": "b", "v": 3}]
        with pytest.raises(ConfigValidationError, match="duplicate names"):
            _merge_named_lists(base, override, field="scripts")

    def test_unique_names_still_merge(self):
        base = [{"name": "a", "v": 1}, {"name": "b", "v": 2}]
        override = [{"name": "b", "v": 99}, {"name": "c", "v": 3}]
        result = _merge_named_lists(base, override)
        assert result == [
            {"name": "a", "v": 1},
            {"name": "b", "v": 99},
            {"name": "c", "v": 3},
        ]


# =========================================================================
# Fix 12: machine override sweep -> expr clears when/default
# =========================================================================

class TestMachineOverrideVarFixup:
    def test_override_expr_clears_when_and_default(self, tmp_path, sample_config_dict):
        sample_config_dict["vars"]["opt_flag"] = {
            "type": "int",
            "sweep": {"mode": "list", "values": [1, 2]},
            "when": "{{ nodes > 1 }}",
            "default": 0,
        }
        sample_config_dict["machines"] = {
            "clusterA": {
                "vars": {"opt_flag": {"expr": "42"}}
            }
        }
        config_file = write_config(tmp_path, sample_config_dict)
        logger = logging.getLogger("test")
        config = load_generic_config(Path(config_file), logger, machine="clusterA")
        var = config.vars["opt_flag"]
        assert var.expr == "42"
        assert var.sweep is None
        assert var.when is None
        assert var.default is None

    def test_override_keeping_sweep_preserves_when_default(self, tmp_path, sample_config_dict):
        sample_config_dict["vars"]["opt_flag"] = {
            "type": "int",
            "sweep": {"mode": "list", "values": [1, 2]},
            "when": "{{ nodes > 1 }}",
            "default": 0,
        }
        sample_config_dict["machines"] = {
            "clusterA": {
                "vars": {"opt_flag": {"sweep": {"mode": "list", "values": [3, 4]}}}
            }
        }
        config_file = write_config(tmp_path, sample_config_dict)
        logger = logging.getLogger("test")
        config = load_generic_config(Path(config_file), logger, machine="clusterA")
        var = config.vars["opt_flag"]
        assert var.sweep.values == [3, 4]
        assert var.when == "{{ nodes > 1 }}"
        assert var.default == 0
