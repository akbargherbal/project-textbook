"""
runtime/checkpointing.py

Wires up LangGraph's persistent SqliteSaver so that every agent run --
including the orchestrator's execution history, its subagent (task-tool)
decisions, and any paused human-in-the-loop approval state -- is written to
a single file-backed SQLite database at the project root: checkpoints.db.

Design notes
------------
- One checkpoints.db for the whole scaffold (not per-project). Every run,
  across every projects/<slug>/, writes into the same DB, distinguished by
  thread_id (see resolve_thread_id below). This keeps "debug with plain
  SQL" simple: one file, one `checkpoints` table, one `writes` table,
  filterable by thread_id.
- SqliteSaver (langgraph.checkpoint.sqlite) is a synchronous, single-process
  checkpointer. That's the right tradeoff here -- main.py is invoked as a
  one-shot CLI process, not a concurrent server, so we don't need
  AsyncSqliteSaver or Postgres. Re-verify this assumption if this scaffold
  ever grows a server/API in front of it (see LIMITATIONS.md's pattern of
  flagging assumptions worth re-checking).
- thread_id is what LangGraph uses to scope a checkpoint history. Reusing
  the same thread_id on a later `python main.py --resume ...` invocation is
  what makes resuming an interrupted/halted session possible -- LangGraph
  looks up the latest checkpoint for that thread_id and continues from
  there, rather than starting a new run.
- We persist "last thread_id used per project" to a small marker file
  under that project's workspace/ (already read/write for the agent, see
  config/permissions.py) purely as a CLI convenience so `--resume` without
  an explicit `--thread-id` does the right thing. The actual state lives in
  checkpoints.db; the marker file is disposable.

NOTE: the exact SqliteSaver / interrupt / Command surface should be
re-verified against docs.langchain.com/oss/python/deepagents/human-in-the-loop
and docs.langchain.com/oss/python/langgraph/persistence before relying on
this in anything beyond this scaffold -- this is the same "re-verify
before shipping" caution LIMITATIONS.md already asks for re:
create_deep_agent's signature.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

# Single, shared, file-backed checkpoint DB at the project root.
CHECKPOINT_DB_PATH = Path(__file__).resolve().parent.parent / "checkpoints.db"


def get_checkpointer(db_path: Path = CHECKPOINT_DB_PATH) -> SqliteSaver:
    """
    Build (and initialize) the persistent SqliteSaver.

    check_same_thread=False: the CLI is single-threaded in practice, but
    SqliteSaver's own lock only guards concurrent access from *this*
    connection object -- disabling sqlite3's same-thread check is the
    documented way to hand that connection to SqliteSaver safely.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()  # idempotent: creates `checkpoints` / `writes` tables if absent
    return saver


def _thread_marker_path(project_dir: Path) -> Path:
    # Lives under workspace/ so it's covered by the project's existing
    # read/write permission rule (config/permissions.py rule 4) rather than
    # needing a new one. Prefixed with "." to signal it's CLI bookkeeping,
    # not an agent-authored artifact.
    return project_dir / "workspace" / ".last_thread_id"


def resolve_thread_id(
    project_dir: Path,
    project_slug: str,
    explicit_thread_id: str | None,
    resume: bool,
) -> tuple[str, bool]:
    """
    Decide which thread_id this invocation should use.

    Returns (thread_id, is_resuming_last_known_thread).

    Rules:
      - --thread-id always wins if given, whether or not --resume is set.
      - --resume with no --thread-id reuses the last thread_id recorded for
        this project (if any); if none is on record, we fall back to a
        fresh thread_id and tell the caller resumption wasn't possible.
      - No --resume and no --thread-id: always mint a fresh thread_id (new
        session), and record it as "last" for a future --resume.
    """
    marker = _thread_marker_path(project_dir)

    if explicit_thread_id:
        thread_id = explicit_thread_id
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(thread_id, encoding="utf-8")
        return thread_id, resume

    if resume and marker.exists():
        thread_id = marker.read_text(encoding="utf-8").strip()
        if thread_id:
            return thread_id, True

    # Fresh session.
    thread_id = f"{project_slug}-{uuid.uuid4().hex[:12]}"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(thread_id, encoding="utf-8")
    return thread_id, False
