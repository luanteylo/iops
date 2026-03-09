"""Tests for JUBE XML to IOPS YAML conversion."""

import pytest
import textwrap
from pathlib import Path
from collections import OrderedDict

jube = pytest.importorskip("jube", reason="JUBE library not installed")


# ---------------------------------------------------------------------------
# Syntax conversion tests
# ---------------------------------------------------------------------------
from iops.convert.jube_syntax import (
    jube_var_to_jinja2,
    jube_python_expr_to_jinja2,
    jube_type_to_iops_type,
    jube_pattern_to_python_regex,
)


class TestJubeVarToJinja2:
    """Test JUBE $var -> {{ var }} conversion."""

    def test_simple_dollar_var(self):
        assert jube_var_to_jinja2("$nodes") == "{{ nodes }}"

    def test_braced_var(self):
        assert jube_var_to_jinja2("${nodes}") == "{{ nodes }}"

    def test_multiple_vars(self):
        result = jube_var_to_jinja2("$nodes and $ppn")
        assert result == "{{ nodes }} and {{ ppn }}"

    def test_mixed_syntax(self):
        result = jube_var_to_jinja2("${nodes}_$ppn")
        assert result == "{{ nodes }}_{{ ppn }}"

    def test_escaped_dollar(self):
        assert jube_var_to_jinja2("$$HOME") == "$HOME"

    def test_no_vars(self):
        assert jube_var_to_jinja2("plain text") == "plain text"

    def test_empty_string(self):
        assert jube_var_to_jinja2("") == ""

    def test_none(self):
        assert jube_var_to_jinja2(None) is None

    def test_jube_internal_vars_preserved(self):
        """JUBE internal vars ($jube_*) should not be converted."""
        assert jube_var_to_jinja2("$jube_wp_id") == "$jube_wp_id"
        assert jube_var_to_jinja2("${jube_wp_id}") == "${jube_wp_id}"

    def test_var_in_command(self):
        result = jube_var_to_jinja2("mpirun -np $np ./benchmark --size $size")
        assert result == "mpirun -np {{ np }} ./benchmark --size {{ size }}"

    def test_var_with_underscores(self):
        assert jube_var_to_jinja2("$my_long_var") == "{{ my_long_var }}"


class TestJubePythonExprToJinja2:
    """Test JUBE python expression -> Jinja2 expr conversion."""

    def test_simple_multiplication(self):
        result = jube_python_expr_to_jinja2("$nodes * $ppn")
        assert result == "{{ nodes * ppn }}"

    def test_braced_vars(self):
        result = jube_python_expr_to_jinja2("${nodes} * ${ppn}")
        assert result == "{{ nodes * ppn }}"

    def test_complex_expression(self):
        result = jube_python_expr_to_jinja2("($volume * 1024) // ($nodes * $ppn)")
        assert result == "{{ (volume * 1024) // (nodes * ppn) }}"

    def test_empty(self):
        assert jube_python_expr_to_jinja2("") == ""

    def test_none(self):
        assert jube_python_expr_to_jinja2(None) is None


class TestJubeTypeMapping:
    """Test JUBE -> IOPS type mapping."""

    def test_string_to_str(self):
        assert jube_type_to_iops_type("string") == "str"

    def test_int_passthrough(self):
        assert jube_type_to_iops_type("int") == "int"

    def test_float_passthrough(self):
        assert jube_type_to_iops_type("float") == "float"

    def test_bool_passthrough(self):
        assert jube_type_to_iops_type("bool") == "bool"

    def test_unknown_defaults_to_str(self):
        assert jube_type_to_iops_type("unknown") == "str"


class TestJubePatternMacros:
    """Test JUBE pattern macro expansion."""

    def test_int_pattern(self):
        result = jube_pattern_to_python_regex("value = $jube_pat_int")
        assert result == r"value = ([+-]?\d+)"

    def test_fp_pattern(self):
        result = jube_pattern_to_python_regex("rate: $jube_pat_fp")
        assert "([+-]?" in result

    def test_word_pattern(self):
        result = jube_pattern_to_python_regex("name: $jube_pat_wrd")
        assert result == r"name: (\S+)"

    def test_no_macros(self):
        assert jube_pattern_to_python_regex(r"value = (\d+)") == r"value = (\d+)"

    def test_empty(self):
        assert jube_pattern_to_python_regex("") == ""

    def test_none(self):
        assert jube_pattern_to_python_regex(None) is None

    def test_multiple_macros(self):
        result = jube_pattern_to_python_regex("$jube_pat_wrd = $jube_pat_int")
        assert r"(\S+)" in result
        assert r"([+-]?\d+)" in result


# ---------------------------------------------------------------------------
# Converter tests
# ---------------------------------------------------------------------------
from iops.convert.jube_converter import JubeConverter, _python_cast_for_type


class TestPythonCastForType:
    """Test the type cast helper."""

    def test_int(self):
        assert _python_cast_for_type("int") == "int"

    def test_float(self):
        assert _python_cast_for_type("float") == "float"

    def test_string(self):
        assert _python_cast_for_type("string") == "str"

    def test_unknown(self):
        assert _python_cast_for_type("other") == "str"


class TestParameterConversion:
    """Test JUBE parameter to IOPS var conversion."""

    def _make_converter(self):
        """Create a converter with a dummy input file."""
        return JubeConverter(
            input_file=Path("/dummy/test.xml"),
            executor="local",
        )

    def test_template_parameter_to_sweep(self):
        """Template parameters (multi-value) should become sweep vars."""
        from jube.parameter import Parameter

        param = Parameter.create_parameter(
            name="nodes",
            value="1,2,4,8",
            separator=",",
            parameter_type="int",
            parameter_mode="text",
        )

        converter = self._make_converter()
        result = converter._convert_parameter(param)

        assert result is not None
        assert result["type"] == "int"
        assert "sweep" in result
        assert result["sweep"]["mode"] == "list"
        assert result["sweep"]["values"] == [1, 2, 4, 8]

    def test_static_parameter(self):
        """Static parameters should become single-value sweep vars."""
        from jube.parameter import Parameter

        param = Parameter.create_parameter(
            name="workdir",
            value="/tmp/bench",
            parameter_type="string",
            parameter_mode="text",
        )

        converter = self._make_converter()
        result = converter._convert_parameter(param)

        assert result is not None
        assert result["type"] == "str"
        assert "sweep" in result
        assert result["sweep"]["values"] == ["/tmp/bench"]

    def test_python_mode_parameter(self):
        """Python-mode parameters should become expr vars."""
        from jube.parameter import Parameter

        param = Parameter.create_parameter(
            name="total_procs",
            value="$nodes * $ppn",
            parameter_type="int",
            parameter_mode="python",
        )

        converter = self._make_converter()
        result = converter._convert_parameter(param)

        assert result is not None
        assert result["type"] == "int"
        assert "expr" in result
        assert result["expr"] == "{{ nodes * ppn }}"

    def test_shell_mode_warns(self):
        """Shell-mode parameters should produce a warning."""
        from jube.parameter import Parameter

        param = Parameter.create_parameter(
            name="hostname",
            value="hostname -f",
            parameter_type="string",
            parameter_mode="shell",
        )

        converter = self._make_converter()
        result = converter._convert_parameter(param)

        assert result is not None
        assert "TODO_shell_mode" in result["expr"]
        assert len(converter.warnings) == 1
        assert "shell mode" in converter.warnings[0]

    def test_jube_internal_skipped(self):
        """Parameters starting with jube_ should be skipped."""
        from jube.parameter import Parameter

        param = Parameter.create_parameter(
            name="jube_wp_id",
            value="0",
            parameter_type="int",
            parameter_mode="text",
        )

        converter = self._make_converter()
        result = converter._convert_parameter(param)

        assert result is None

    def test_param_referencing_other_vars(self):
        """Parameters referencing other vars via $var should become expr."""
        from jube.parameter import Parameter

        param = Parameter.create_parameter(
            name="output_path",
            value="$workdir/results/$nodes",
            parameter_type="string",
            parameter_mode="text",
        )

        converter = self._make_converter()
        result = converter._convert_parameter(param)

        assert result is not None
        assert "expr" in result
        assert "{{ workdir }}" in result["expr"]
        assert "{{ nodes }}" in result["expr"]


# ---------------------------------------------------------------------------
# Integration test with XML parsing
# ---------------------------------------------------------------------------
class TestXMLConversion:
    """Integration tests parsing real JUBE XML and converting to IOPS."""

    MINIMAL_XML = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <jube>
          <benchmark name="test_bench" outpath="bench_run">
            <comment>A test benchmark</comment>

            <parameterset name="params">
              <parameter name="nodes" type="int">1,2,4</parameter>
              <parameter name="ppn" type="int">8</parameter>
              <parameter name="total_procs" type="int" mode="python">$nodes * $ppn</parameter>
            </parameterset>

            <step name="execute" work_dir="work">
              <use>params</use>
              <do>mpirun -np $total_procs ./benchmark --nodes $nodes</do>
              <do>echo "done"</do>
            </step>

            <patternset name="patterns">
              <pattern name="throughput" type="float">Throughput: $jube_pat_fp MB/s</pattern>
              <pattern name="runtime" type="float">Runtime: $jube_pat_fp seconds</pattern>
            </patternset>

            <analyser name="analyse">
              <use>patterns</use>
              <analyse step="execute">
                <file>stdout</file>
              </analyse>
            </analyser>

            <result>
              <use>analyse</use>
              <table name="result" style="csv">
                <column>nodes</column>
                <column>throughput</column>
                <column>runtime</column>
              </table>
            </result>
          </benchmark>
        </jube>
    """)

    @pytest.fixture
    def xml_file(self, tmp_path):
        """Create a temporary JUBE XML file."""
        xml_path = tmp_path / "test_bench.xml"
        xml_path.write_text(self.MINIMAL_XML)
        return xml_path

    def test_parse_and_convert(self, xml_file):
        """Test end-to-end conversion from XML to IOPS config dict."""
        converter = JubeConverter(input_file=xml_file, executor="local")
        config, warnings = converter.convert()

        # Check benchmark section
        assert config["benchmark"]["name"] == "test_bench"
        assert config["benchmark"]["description"] == "A test benchmark"
        assert config["benchmark"]["executor"] == "local"

        # Check vars section
        assert "nodes" in config["vars"]
        assert config["vars"]["nodes"]["type"] == "int"
        assert config["vars"]["nodes"]["sweep"]["values"] == [1, 2, 4]

        assert "ppn" in config["vars"]
        assert config["vars"]["ppn"]["sweep"]["values"] == [8]

        assert "total_procs" in config["vars"]
        assert "expr" in config["vars"]["total_procs"]
        assert "nodes * ppn" in config["vars"]["total_procs"]["expr"]

        # Check command section
        assert "command" in config
        assert "{{ total_procs }}" in config["command"]["template"]
        assert "{{ nodes }}" in config["command"]["template"]

        # Check scripts section
        assert len(config["scripts"]) == 1
        script = config["scripts"][0]
        assert script["name"] == "main"
        assert script["submit"] == "bash"
        assert "{{ command.template }}" in script["script_template"]

        # Check parser section
        assert "parser" in script
        assert "throughput" in str(script["parser"]["metrics"])
        assert "runtime" in str(script["parser"]["metrics"])
        assert "def parse(file_path):" in script["parser"]["parser_script"]

    def test_write_yaml_dry_run(self, xml_file, capsys):
        """Test dry-run prints YAML to stdout."""
        converter = JubeConverter(input_file=xml_file, executor="local")
        config, _ = converter.convert()
        result = converter.write_yaml(config, dry_run=True)

        assert result is None
        captured = capsys.readouterr()
        assert "benchmark:" in captured.out
        assert "vars:" in captured.out

    def test_write_yaml_to_file(self, xml_file, tmp_path):
        """Test writing YAML to a file."""
        output = tmp_path / "output.yaml"
        converter = JubeConverter(input_file=xml_file, executor="local")
        config, _ = converter.convert()
        result = converter.write_yaml(config, output_file=output)

        assert result == output
        assert output.exists()
        content = output.read_text()
        assert "benchmark:" in content
        assert "Converted from JUBE XML" in content

    def test_slurm_executor(self, xml_file):
        """Test conversion with SLURM executor."""
        converter = JubeConverter(input_file=xml_file, executor="slurm")
        config, _ = converter.convert()

        assert config["benchmark"]["executor"] == "slurm"
        script = config["scripts"][0]
        assert script["submit"] == "sbatch"
        assert "#SBATCH" in script["script_template"]

    def test_benchmark_selection(self, xml_file):
        """Test error when selecting non-existent benchmark."""
        converter = JubeConverter(
            input_file=xml_file,
            benchmark_name="nonexistent",
        )
        with pytest.raises(ValueError, match="not found"):
            converter.convert()


MULTI_BENCH_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <jube>
      <benchmark name="bench_a" outpath="out_a">
        <parameterset name="params">
          <parameter name="x" type="int">1</parameter>
        </parameterset>
        <step name="run">
          <use>params</use>
          <do>echo $x</do>
        </step>
      </benchmark>
      <benchmark name="bench_b" outpath="out_b">
        <parameterset name="params">
          <parameter name="y" type="int">2</parameter>
        </parameterset>
        <step name="run">
          <use>params</use>
          <do>echo $y</do>
        </step>
      </benchmark>
    </jube>
""")


class TestMultiBenchmarkXML:
    """Tests for XML files containing multiple benchmarks."""

    @pytest.fixture
    def xml_file(self, tmp_path):
        xml_path = tmp_path / "multi.xml"
        xml_path.write_text(MULTI_BENCH_XML)
        return xml_path

    def test_error_without_selection(self, xml_file):
        """Multiple benchmarks without --benchmark should raise ValueError."""
        converter = JubeConverter(input_file=xml_file)
        with pytest.raises(ValueError, match="Multiple benchmarks"):
            converter.convert()

    def test_select_specific_benchmark(self, xml_file):
        """Selecting a specific benchmark should work."""
        converter = JubeConverter(input_file=xml_file, benchmark_name="bench_a")
        config, _ = converter.convert()
        assert config["benchmark"]["name"] == "bench_a"
        assert "x" in config["vars"]

    def test_select_other_benchmark(self, xml_file):
        """Selecting the other benchmark should work."""
        converter = JubeConverter(input_file=xml_file, benchmark_name="bench_b")
        config, _ = converter.convert()
        assert config["benchmark"]["name"] == "bench_b"
        assert "y" in config["vars"]


# ---------------------------------------------------------------------------
# Public API test
# ---------------------------------------------------------------------------
from iops.convert import convert_jube_to_iops


class TestPublicAPI:
    """Test the public convert_jube_to_iops function."""

    SIMPLE_XML = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <jube>
          <benchmark name="simple" outpath="out">
            <parameterset name="params">
              <parameter name="size" type="int">100</parameter>
            </parameterset>
            <step name="run">
              <use>params</use>
              <do>echo $size</do>
            </step>
          </benchmark>
        </jube>
    """)

    @pytest.fixture
    def xml_file(self, tmp_path):
        xml_path = tmp_path / "simple.xml"
        xml_path.write_text(self.SIMPLE_XML)
        return xml_path

    def test_default_output_path(self, xml_file, tmp_path):
        """Default output should be <stem>_iops.yaml."""
        result = convert_jube_to_iops(xml_file)
        expected = xml_file.with_name("simple_iops.yaml")
        assert result == expected
        assert expected.exists()

    def test_custom_output_path(self, xml_file, tmp_path):
        """Custom output path should be respected."""
        output = tmp_path / "custom.yaml"
        result = convert_jube_to_iops(xml_file, output_file=output)
        assert result == output
        assert output.exists()

    def test_dry_run(self, xml_file, capsys):
        """Dry run should print to stdout and return None."""
        result = convert_jube_to_iops(xml_file, dry_run=True)
        assert result is None
        captured = capsys.readouterr()
        assert "benchmark:" in captured.out

    def test_file_not_found(self, tmp_path):
        """Non-existent input file should raise an error."""
        # The JUBE parser will raise its own error for missing files
        with pytest.raises(Exception):
            convert_jube_to_iops(tmp_path / "nonexistent.xml")
