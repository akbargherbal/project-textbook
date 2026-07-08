"""
tests/scripts/test_fetch_sources.py

Mock subprocess.run -- never invoke real git.
"""

import subprocess

import pytest
import yaml

import scripts.fetch_sources as fetch_sources

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(fetch_sources, "PROJECTS_DIR", projects_dir)
    return projects_dir


def _write_config(projects_dir, slug, **overrides):
    project_dir = projects_dir / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "project_name": slug,
        "framework_name": "Django",
        "target_repo": {"source": "local"},
        "framework_docs": {"source": "local"},
    }
    cfg.update(overrides)
    (project_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    return project_dir


def test_fetch_with_local_source_does_not_call_subprocess(fake_projects_dir, mocker):
    _write_config(fake_projects_dir, "demo")
    mock_run = mocker.patch("scripts.fetch_sources.subprocess.run")
    fetch_sources.fetch("demo")
    mock_run.assert_not_called()


def test_fetch_with_git_source_and_no_ref_warns_but_still_clones(
    fake_projects_dir, mocker, capsys
):
    _write_config(
        fake_projects_dir,
        "demo",
        framework_docs={
            "source": "git",
            "git_url": "https://example.invalid/repo.git",
            "ref": None,
            "subpath": None,
        },
    )
    mocker.patch(
        "scripts.fetch_sources.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        ),
    )
    fetch_sources.fetch("demo")
    captured = capsys.readouterr()
    assert "no ref pinned" in captured.out.lower()


def test_clone_builds_correct_command_with_ref(tmp_path, mocker):
    mock_run = mocker.patch(
        "scripts.fetch_sources.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        ),
    )
    dest = tmp_path / "dest"

    # Since subprocess.run is mocked, the real tempdir will stay empty --
    # simulate a successful clone by patching tempfile to a real dir we
    # control and pre-populating it before _clone checks the subpath.
    import tempfile as real_tempfile

    class _FakeTmp:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return str(self.path)

        def __exit__(self, *a):
            pass

    fake_tmp_dir = tmp_path / "faketmp"
    fake_tmp_dir.mkdir()
    mocker.patch(
        "scripts.fetch_sources.tempfile.TemporaryDirectory",
        return_value=_FakeTmp(fake_tmp_dir),
    )

    fetch_sources._clone("https://example.invalid/repo.git", "stable/5.1.x", dest, None)

    cmd = mock_run.call_args[0][0]
    assert cmd == [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        "stable/5.1.x",
        "https://example.invalid/repo.git",
        str(fake_tmp_dir),
    ]


def test_clone_omits_branch_flag_when_ref_is_none(tmp_path, mocker):
    mock_run = mocker.patch(
        "scripts.fetch_sources.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        ),
    )
    dest = tmp_path / "dest"

    class _FakeTmp:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return str(self.path)

        def __exit__(self, *a):
            pass

    fake_tmp_dir = tmp_path / "faketmp"
    fake_tmp_dir.mkdir()
    mocker.patch(
        "scripts.fetch_sources.tempfile.TemporaryDirectory",
        return_value=_FakeTmp(fake_tmp_dir),
    )

    fetch_sources._clone("https://example.invalid/repo.git", None, dest, None)

    cmd = mock_run.call_args[0][0]
    assert "--branch" not in cmd
    assert cmd == [
        "git",
        "clone",
        "--depth",
        "1",
        "https://example.invalid/repo.git",
        str(fake_tmp_dir),
    ]


def test_clone_nonzero_returncode_exits_1(tmp_path, mocker):
    mocker.patch(
        "scripts.fetch_sources.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="fatal: repository not found"
        ),
    )
    dest = tmp_path / "dest"
    with pytest.raises(SystemExit) as exc_info:
        fetch_sources._clone("https://example.invalid/repo.git", None, dest, None)
    assert exc_info.value.code == 1


def test_clone_missing_subpath_in_cloned_tree_exits_1_distinctly(tmp_path, mocker):
    """Uses a real temp directory for the 'cloned' content (only the git
    clone subprocess call itself is mocked) -- the subpath-existence
    check touches the real filesystem."""
    mocker.patch(
        "scripts.fetch_sources.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        ),
    )
    dest = tmp_path / "dest"
    # Real tempfile.TemporaryDirectory is used (not mocked) -- it will be
    # empty since subprocess.run is mocked and never actually clones
    # anything into it, so "docs" subpath will not exist inside it.
    with pytest.raises(SystemExit) as exc_info:
        fetch_sources._clone("https://example.invalid/repo.git", None, dest, "docs")
    assert exc_info.value.code == 1


def test_clone_overwrites_existing_dest_directory(tmp_path, mocker):
    mocker.patch(
        "scripts.fetch_sources.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        ),
    )

    dest = tmp_path / "dest"
    dest.mkdir()
    stray_file = dest / "stray.txt"
    stray_file.write_text("should be gone after _clone")

    class _FakeTmp:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return str(self.path)

        def __exit__(self, *a):
            pass

    fake_tmp_dir = tmp_path / "faketmp"
    fake_tmp_dir.mkdir()
    (fake_tmp_dir / "new_content.txt").write_text("fresh clone content")
    mocker.patch(
        "scripts.fetch_sources.tempfile.TemporaryDirectory",
        return_value=_FakeTmp(fake_tmp_dir),
    )

    fetch_sources._clone("https://example.invalid/repo.git", None, dest, None)

    assert not stray_file.exists()
    assert (dest / "new_content.txt").exists()


def test_fetch_missing_config_yaml_exits_1_cleanly(fake_projects_dir):
    # No config.yaml written for this slug at all.
    with pytest.raises(SystemExit) as exc_info:
        fetch_sources.fetch("nonexistent-project")
    assert exc_info.value.code == 1


def test_fetch_target_repo_local_prints_message_no_clone(
    fake_projects_dir, mocker, capsys
):
    _write_config(fake_projects_dir, "demo")
    mock_run = mocker.patch("scripts.fetch_sources.subprocess.run")
    fetch_sources.fetch("demo")
    mock_run.assert_not_called()
    captured = capsys.readouterr()
    assert (
        "nothing to fetch" in captured.out.lower() or "yourself" in captured.out.lower()
    )
