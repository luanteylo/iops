import tempfile
from jinja2 import TemplateNotFound
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from iops.benchmarks.ior import IORBenchmark

@pytest.fixture
def mock_script_generator(tmp_path):
    """Fixture to mock the script generator for IORBenchmark."""
    template_path = tmp_path / "template.sh"
    template_content = "#!/bin/bash\necho 'IOR test: {{ nodes }} nodes, {{ ntasks_per_node }} tasks per node'\n"
    template_path.write_text(template_content)

    # Create a dummy config object with the template path
    class DummyConfig:
        def __init__(self):
            self.template = MagicMock()
            # Set only the filename for Jinja2 to find by name
            self.template.bash_template = template_path

    return DummyConfig()

def test_script_is_generated(tmp_path, mock_script_generator):
    """Test that the IOR script is generated successfully."""
    dummy_config = mock_script_generator
    benchmark = IORBenchmark(dummy_config)

    
    params = {
        "nodes": 2,
        "processes_per_node": 2,
        "__test_folder": str(tmp_path),
        "__test_output": str(tmp_path / "output.txt"),
        "ost_count": str(tmp_path),
        "volume": 1024,
        "__test_script": str(tmp_path / "test_script.sh"),
    }
    
    script = benchmark.generate(params)

    assert script.exists()
    assert script.read_text() == "#!/bin/bash\necho 'IOR test: 2 nodes, 2 tasks per node'"


def test_raises_when_template_file_is_missing(tmp_path, mock_script_generator):
    """Test that an error is raised when the template file is missing."""
    dummy_config = mock_script_generator
    # Remove the template file to simulate missing template
    dummy_config.template.bash_template.unlink()

    benchmark = IORBenchmark(dummy_config)
    params = {
        "nodes": 2,
        "processes_per_node": 2,
        "__test_folder": str(tmp_path),
        "__test_output": str(tmp_path / "output.txt"),
        "ost_count": str(tmp_path),
        "volume": 1024,
        "__test_script": str(tmp_path / "test_script.sh"),
    }

    with pytest.raises(TemplateNotFound):
        benchmark.generate(params)

