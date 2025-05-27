import sys
import pytest
from unittest.mock import patch
from pathlib import Path


@patch("iops.main.FileUtils")
def test_generate_setup_triggers_generation(MockFileUtils, tmp_path, monkeypatch):
    test_path = tmp_path / "config.ini"

    # Simulate CLI call: iops.main --generate_setup config.ini
    monkeypatch.setattr(sys, "argv", ["main.py", "--generate_setup", str(test_path)])
    from iops import main
    main.main()

    MockFileUtils.return_value.generate_iops_config.assert_called_once_with(test_path)

    # Simulate --generate_setup with no path
    monkeypatch.setattr(sys, "argv", ["main.py", "--generate_setup"])
    main.main()

    MockFileUtils.return_value.generate_iops_config.assert_called_with(Path("iops_config.ini"))


@patch("iops.main.FileUtils")
def test_generate_setup_default_filename(MockFileUtils, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--generate_setup"])
    from iops import main
    main.main()
    MockFileUtils.return_value.generate_iops_config.assert_called_once_with(Path("iops_config.ini"))
