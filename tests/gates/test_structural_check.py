"""
tests/gates/test_structural_check.py

Pure, deterministic file-existence + line-range logic. No mocking beyond
tmp_path (via the project_dir fixture).
"""

import pytest

from gates import structural_check

pytestmark = pytest.mark.unit


def test_missing_repo_reference_fails(project_dir):
    result = structural_check.check({}, project_dir)
    assert result["passed"] is False
    assert "No repo_reference provided" in result["reason"]


def test_empty_repo_reference_fails(project_dir):
    result = structural_check.check({"repo_reference": ""}, project_dir)
    assert result["passed"] is False


def test_file_does_not_exist_fails(project_dir):
    result = structural_check.check(
        {"repo_reference": "does_not_exist.py"}, project_dir
    )
    assert result["passed"] is False
    assert "does not exist in target_repo/" in result["reason"]
    assert "does_not_exist.py" in result["reason"]


def test_bare_file_reference_that_exists_passes(project_dir):
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    result = structural_check.check({"repo_reference": "app.py"}, project_dir)
    assert result["passed"] is True


def test_line_in_range_passes(project_dir):
    f = project_dir / "target_repo" / "app.py"
    f.write_text("line1\nline2\nline3\n")
    result = structural_check.check({"repo_reference": "app.py:2"}, project_dir)
    assert result["passed"] is True


def test_line_zero_fails(project_dir):
    f = project_dir / "target_repo" / "app.py"
    f.write_text("line1\nline2\n")
    result = structural_check.check({"repo_reference": "app.py:0"}, project_dir)
    assert result["passed"] is False
    assert "out of range" in result["reason"]


def test_line_out_of_range_fails(project_dir):
    f = project_dir / "target_repo" / "app.py"
    f.write_text("line1\nline2\n")
    result = structural_check.check({"repo_reference": "app.py:99"}, project_dir)
    assert result["passed"] is False
    assert "out of range" in result["reason"]


def test_range_end_before_start_fails(project_dir):
    f = project_dir / "target_repo" / "app.py"
    f.write_text("line1\nline2\nline3\n")
    result = structural_check.check({"repo_reference": "app.py:3-1"}, project_dir)
    assert result["passed"] is False
    assert "end before start" in result["reason"]


def test_range_end_out_of_range_fails(project_dir):
    f = project_dir / "target_repo" / "app.py"
    f.write_text("line1\nline2\n")
    result = structural_check.check({"repo_reference": "app.py:1-99"}, project_dir)
    assert result["passed"] is False
    assert "out of range" in result["reason"]


def test_valid_range_passes(project_dir):
    f = project_dir / "target_repo" / "app.py"
    f.write_text("line1\nline2\nline3\nline4\n")
    result = structural_check.check({"repo_reference": "app.py:1-3"}, project_dir)
    assert result["passed"] is True


def test_windows_backslash_reference_is_not_normalized(project_dir):
    """
    structural_check.py does NOT normalize backslashes -- only main.py's
    parser does that. A Windows-style path is treated as a literal
    (non-existent, on POSIX) path segment and fails, documenting this
    module's behavior rather than assuming it "just works."
    """
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    result = structural_check.check(
        {"repo_reference": "target_repo\\app.py"}, project_dir
    )
    assert result["passed"] is False
