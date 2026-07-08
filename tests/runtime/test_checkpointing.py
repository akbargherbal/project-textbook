"""
tests/runtime/test_checkpointing.py

Real SQLite is cheap -- don't mock it, just point everything at
tmp_path.
"""

import re
import sqlite3

import pytest

from runtime.checkpointing import get_checkpointer, resolve_thread_id

pytestmark = pytest.mark.unit


def test_get_checkpointer_creates_db_and_tables(tmp_path):
    db_path = tmp_path / "checkpoints.db"
    assert not db_path.exists()

    get_checkpointer(db_path)

    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "checkpoints" in tables
    assert "writes" in tables


def test_get_checkpointer_is_idempotent(tmp_path):
    db_path = tmp_path / "checkpoints.db"
    get_checkpointer(db_path)
    # Second call against the same path should not raise.
    get_checkpointer(db_path)


def test_explicit_thread_id_always_wins(project_dir):
    thread_id, is_resuming = resolve_thread_id(
        project_dir, "demo-project", explicit_thread_id="my-thread", resume=False
    )
    assert thread_id == "my-thread"
    marker = project_dir / "workspace" / ".last_thread_id"
    assert marker.read_text() == "my-thread"


def test_explicit_thread_id_wins_even_with_resume_true(project_dir):
    thread_id, is_resuming = resolve_thread_id(
        project_dir, "demo-project", explicit_thread_id="my-thread", resume=True
    )
    assert thread_id == "my-thread"
    assert is_resuming is True


def test_resume_with_no_marker_file_mints_fresh_id(project_dir):
    thread_id, is_resuming = resolve_thread_id(
        project_dir, "demo-project", explicit_thread_id=None, resume=True
    )
    assert is_resuming is False
    assert thread_id.startswith("demo-project-")


def test_resume_with_existing_marker_file_reuses_it(project_dir):
    marker = project_dir / "workspace" / ".last_thread_id"
    marker.write_text("previous-thread-id")

    thread_id, is_resuming = resolve_thread_id(
        project_dir, "demo-project", explicit_thread_id=None, resume=True
    )
    assert thread_id == "previous-thread-id"
    assert is_resuming is True


def test_no_resume_no_explicit_id_mints_fresh_thread_id_with_correct_shape(project_dir):
    thread_id, is_resuming = resolve_thread_id(
        project_dir, "demo-project", explicit_thread_id=None, resume=False
    )
    assert is_resuming is False
    assert re.match(r"^demo-project-[0-9a-f]{12}$", thread_id)


def test_two_fresh_calls_produce_different_thread_ids(project_dir):
    thread_id_1, _ = resolve_thread_id(
        project_dir, "demo-project", explicit_thread_id=None, resume=False
    )
    thread_id_2, _ = resolve_thread_id(
        project_dir, "demo-project", explicit_thread_id=None, resume=False
    )
    assert thread_id_1 != thread_id_2


def test_fresh_session_persists_marker_for_future_resume(project_dir):
    thread_id, _ = resolve_thread_id(
        project_dir, "demo-project", explicit_thread_id=None, resume=False
    )
    marker = project_dir / "workspace" / ".last_thread_id"
    assert marker.read_text() == thread_id
