"""
gates/structural_check.py

Structural axis: does the file/line/symbol a mapping claims to reference
actually exist in projects/<slug>/target_repo/? Reads the real filesystem
-- not the agent's report of it. This file is in gates/, write/execute-
denied to the agent per config/permissions.py -- the gate cannot be
edited by the thing it's checking.

Run outside the agent loop, before anything is persisted to
projects/<slug>/workspace/mappings/.
"""
import re
from pathlib import Path


def check(mapping_entry: dict, project_dir: Path) -> dict:
    """
    mapping_entry expected shape (see AGENTS.md house style):
      {
        "repo_reference": "path/to/file.py:40",   # or "path/to/file.py"
        "concept": "...",
        ...
      }

    Returns {"passed": bool, "reason": str}
    """
    ref = mapping_entry.get("repo_reference", "")
    if not ref:
        return {"passed": False, "reason": "No repo_reference provided to check."}

    match = re.match(r"^(.*?)(?::(\d+)(?:-(\d+))?)?$", ref)
    file_part, line_start, line_end = match.group(1), match.group(2), match.group(3)

    file_path = project_dir / "target_repo" / file_part
    if not file_path.exists():
        return {
            "passed": False,
            "reason": f"Referenced file does not exist in target_repo/: {file_part}",
        }

    if line_start:
        line_start_num = int(line_start)
        try:
            lines = file_path.read_text(errors="replace").splitlines()
        except Exception as e:
            return {"passed": False, "reason": f"Could not read {file_part}: {e}"}
        if line_start_num < 1 or line_start_num > len(lines):
            return {
                "passed": False,
                "reason": (
                    f"Referenced line {line_start_num} out of range for "
                    f"{file_part} ({len(lines)} lines)."
                ),
            }
        if line_end:
            line_end_num = int(line_end)
            if line_end_num < 1 or line_end_num > len(lines):
                return {
                    "passed": False,
                    "reason": (
                        f"Referenced line {line_end_num} out of range for "
                        f"{file_part} ({len(lines)} lines)."
                    ),
                }
            if line_end_num < line_start_num:
                return {
                    "passed": False,
                    "reason": (
                        f"Referenced line range {line_start_num}-{line_end_num} "
                        f"is invalid for {file_part} (end before start)."
                    ),
                }

    return {"passed": True, "reason": "Reference exists in target_repo/."}
