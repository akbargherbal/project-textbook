"""
tests/gates/test_freshness_check.py

Mocks nothing -- real pyproject.toml/requirements.txt/etc. files written
into tmp_path / "target_repo".
"""

import yaml
import pytest

from gates import freshness_check

pytestmark = pytest.mark.unit


def _write_config(project_dir, **overrides):
    cfg = {
        "framework_name": "Django",
        "framework_docs": {"ref": "stable/5.1.x"},
    }
    cfg.update(overrides)
    (project_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    return cfg


def test_missing_framework_name_fails(project_dir):
    _write_config(project_dir, framework_name="")
    result = freshness_check.check(project_dir)
    assert result["passed"] is False
    assert "missing framework_name" in result["reason"]


def test_missing_docs_ref_fails(project_dir):
    _write_config(project_dir, framework_docs={"ref": None})
    result = freshness_check.check(project_dir)
    assert result["passed"] is False
    assert "not pinned" in result["reason"]


def test_no_manifest_file_passes_as_unverifiable(project_dir):
    """Counterintuitive: no manifest match is a PASS, not a failure."""
    _write_config(project_dir)
    result = freshness_check.check(project_dir)
    assert result["passed"] is True
    assert "unverifiable" in result["reason"]


def test_matching_major_minor_passes(project_dir):
    _write_config(
        project_dir, framework_name="Django", framework_docs={"ref": "stable/5.1.x"}
    )
    (project_dir / "target_repo" / "requirements.txt").write_text("Django==5.1.4\n")
    result = freshness_check.check(project_dir)
    assert result["passed"] is True
    assert "consistent" in result["reason"]


def test_mismatched_major_minor_fails(project_dir):
    _write_config(
        project_dir, framework_name="Django", framework_docs={"ref": "stable/5.1.x"}
    )
    (project_dir / "target_repo" / "requirements.txt").write_text("Django==4.2.1\n")
    result = freshness_check.check(project_dir)
    assert result["passed"] is False
    assert "VERSION MISMATCH" in result["reason"]


@pytest.mark.parametrize(
    "filename,content",
    [
        ("pyproject.toml", 'dependencies = ["Django>=5.1.4"]\n'),
        ("requirements.txt", "Django==5.1.4\n"),
        ("package.json", '"Django==5.1.4"\n'),
        ("Pipfile", "Django==5.1.4\n"),
    ],
)
def test_manifest_candidates_all_detected(project_dir, filename, content):
    _write_config(
        project_dir, framework_name="Django", framework_docs={"ref": "stable/5.1.x"}
    )
    (project_dir / "target_repo" / filename).write_text(content)
    result = freshness_check.check(project_dir)
    assert result["passed"] is True
    assert "consistent" in result["reason"]
