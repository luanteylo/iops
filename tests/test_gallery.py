"""Unit tests for the per-execution image gallery (reporting.gallery).

Covers:
1. Config parsing and validation of the gallery section
2. The {{ artifacts_dir }} built-in template variable
3. Image discovery (convention folder + explicit sources) and base64 embedding
4. Report rendering of the gallery section, including caption and section toggles
"""

import base64
import json
from pathlib import Path

import pytest
import yaml

from iops.config.models import GalleryConfig, ReportingConfig, SectionConfig
from iops.config.loader import ConfigValidationError, _parse_gallery_config
from iops.execution.matrix import build_execution_matrix
from iops.reporting.report_generator import ReportGenerator
from conftest import load_config


# Smallest valid 1x1 PNG.
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _write_png(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PNG_1x1)


# ============================================================================ #
# Config parsing / validation
# ============================================================================ #

def test_gallery_defaults():
    g = GalleryConfig()
    assert g.enabled is False
    assert g.folder == "images"
    assert g.pattern == "*.png"
    assert g.title == "Image Gallery"


def test_parse_gallery_config_valid():
    g = _parse_gallery_config({
        "enabled": True,
        "folder": "imgs",
        "sources": ["{{ execution_dir }}/final.png"],
        "pattern": "*.jpg",
        "max_width": 512,
        "caption_vars": ["nodes"],
        "title": "Thumbnails",
    })
    assert g.enabled and g.folder == "imgs" and g.max_width == 512
    assert g.sources == ["{{ execution_dir }}/final.png"]
    assert g.caption_vars == ["nodes"]


def test_parse_gallery_rejects_bad_sources():
    with pytest.raises(ConfigValidationError):
        _parse_gallery_config({"sources": "not-a-list"})


def test_parse_gallery_rejects_non_positive_max_width():
    with pytest.raises(ConfigValidationError):
        _parse_gallery_config({"max_width": 0})


def test_parse_gallery_rejects_unknown_key():
    with pytest.raises(ConfigValidationError):
        _parse_gallery_config({"folde": "typo"})


def test_loader_validates_caption_vars_against_real_vars(sample_config_dict, tmp_path):
    sample_config_dict["reporting"] = {
        "enabled": True,
        "gallery": {"enabled": True, "caption_vars": ["does_not_exist"]},
    }
    config_file = tmp_path / "cfg.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError):
        load_config(config_file)


def test_loader_accepts_valid_caption_vars(sample_config_dict, tmp_path):
    sample_config_dict["reporting"] = {
        "enabled": True,
        "gallery": {"enabled": True, "caption_vars": ["nodes"]},
    }
    config_file = tmp_path / "cfg.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert config.reporting.gallery.caption_vars == ["nodes"]


# ============================================================================ #
# {{ artifacts_dir }} built-in
# ============================================================================ #

def test_artifacts_dir_builtin_matches_gallery_folder(sample_config_dict, tmp_path):
    sample_config_dict["reporting"] = {
        "enabled": True,
        "gallery": {"enabled": True, "folder": "thumbs"},
    }
    config_file = tmp_path / "cfg.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)
    config = load_config(config_file)

    kept, _ = build_execution_matrix(config)
    inst = kept[0]
    inst.execution_dir = Path("/run/exec_0001/repetition_001")

    ctx = inst._render_context()
    assert ctx["artifacts_dir"] == "/run/exec_0001/repetition_001/thumbs"


def test_artifacts_dir_defaults_without_gallery(sample_config_file):
    config = load_config(sample_config_file)
    kept, _ = build_execution_matrix(config)
    inst = kept[0]
    inst.execution_dir = Path("/run/exec_0001/repetition_001")
    ctx = inst._render_context()
    assert ctx["artifacts_dir"].endswith("/images")


# ============================================================================ #
# Report rendering
# ============================================================================ #

def _make_gallery_run(tmp_path, n_exec=2, folder="images"):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    index = {"benchmark": "T", "executions": {}}
    for i in range(1, n_exec + 1):
        exec_key = f"exec_{i:04d}"
        rel = f"runs/{exec_key}"
        _write_png(run_dir / rel / "repetition_001" / folder / "final_state.png")
        index["executions"][exec_key] = {
            "path": rel, "params": {"nodes": i, "ppn": 4}, "command": "x"
        }
    (run_dir / "__iops_index.json").write_text(json.dumps(index))
    return run_dir


def _gallery_stub(run_dir, gallery):
    gen = ReportGenerator.__new__(ReportGenerator)
    gen.workdir = run_dir
    gen.report_config = ReportingConfig(sections=SectionConfig(), gallery=gallery)
    return gen


def test_gallery_section_renders_convention_folder(tmp_path):
    run_dir = _make_gallery_run(tmp_path, n_exec=2)
    gallery = GalleryConfig(enabled=True, caption_vars=["nodes", "ppn"], title="Sims")
    html = _gallery_stub(run_dir, gallery)._generate_gallery_section(["nodes"])

    assert "Sims" in html
    assert html.count("iops-gallery-card") == 2          # one card per execution
    assert "data:image/png;base64," in html              # image embedded
    assert "nodes=1, ppn=4" in html                      # caption from params
    assert "iopsLightbox" in html                        # click-to-enlarge handler


def test_gallery_section_empty_when_disabled(tmp_path):
    run_dir = _make_gallery_run(tmp_path)
    gallery = GalleryConfig(enabled=False)
    assert _gallery_stub(run_dir, gallery)._generate_gallery_section([]) == ""


def test_gallery_section_empty_when_no_images(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "__iops_index.json").write_text(json.dumps({"executions": {}}))
    gallery = GalleryConfig(enabled=True)
    assert _gallery_stub(run_dir, gallery)._generate_gallery_section([]) == ""


def test_gallery_custom_folder(tmp_path):
    run_dir = _make_gallery_run(tmp_path, n_exec=1, folder="thumbs")
    gallery = GalleryConfig(enabled=True, folder="thumbs")
    html = _gallery_stub(run_dir, gallery)._generate_gallery_section([])
    assert "data:image/png;base64," in html


def test_image_to_data_uri_unknown_extension(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hi")
    gen = ReportGenerator.__new__(ReportGenerator)
    assert gen._image_to_data_uri(f, None) is None
