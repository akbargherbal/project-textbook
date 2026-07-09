#!/usr/bin/env python3
"""
scripts/recheck_gates.py

Standalone, offline re-run of the three verification gates
(structural_check, citation_validator, freshness_check) against entries
already sitting in workspace/notes/flagged.md, using a persisted tool-call
transcript instead of a live agent run.

WHY THIS EXISTS:
Gate failures aren't always genuine problems with a mapping entry -- they
can also be caused by something external to the entry itself changing
after the fact (a target_repo/ path getting fixed, a doc file moving,
etc.). Before transcript persistence (see agents/tool_call_logger.py's
save_calls/load_calls), the only way to re-check a flagged entry was to
re-run the whole agent, paying for a fresh LLM call just to regenerate
citation evidence that had already been legitimately produced once. This
script re-runs the exact same gate logic main.py's run() uses, but reads
a saved transcript_<thread_id>.jsonl instead of requiring a live
ToolCallLogger -- no model calls, no API keys, no network.

This does NOT invent or "probably fine" its way past a real citation
failure -- it re-runs citation_validator.check() against the SAME
transcript-diff logic main.py always used. If a citation genuinely wasn't
grounded, it will fail here too, correctly. This only helps when the
underlying evidence was fine all along and something unrelated (like a
structural path bug) caused a false flag alongside it.

Usage:
    python scripts/recheck_gates.py --project deep-agents --thread-id deep-agents-d85e7859226d

If --thread-id is omitted, the script looks for exactly one
transcript_*.jsonl under workspace/notes/ and uses that; it errors if
there are zero or more than one, rather than guessing which run to trust.
"""
import argparse
import re
import sys
from pathlib import Path

PROJECTS_DIR = Path(__file__).parent.parent / "projects"

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.tool_call_logger import load_calls, build_transcript_from_calls  # noqa: E402
import gates.structural_check as structural_check  # noqa: E402
import gates.citation_validator as citation_validator  # noqa: E402
import gates.freshness_check as freshness_check  # noqa: E402


def _parse_markdown_mapping(content: str) -> dict:
    """Mirrors main.py's parse_markdown_mapping() exactly -- kept as a
    private copy here rather than importing main.py, since main.py has
    argparse/CLI side effects at import time that this script shouldn't
    trigger."""
    entry = {}

    header_match = re.search(r"^##\s*(.+)$", content, re.MULTILINE)
    entry["repo_reference"] = header_match.group(1).strip() if header_match else ""

    concept_match = re.search(r"\*\*Concept:\*\*\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    if not concept_match:
        concept_match = re.search(r"\*\*Concept\*\*:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    entry["concept"] = concept_match.group(1).strip() if concept_match else ""

    doc_source_match = re.search(r"\*\*Doc source:\*\*\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    if not doc_source_match:
        doc_source_match = re.search(r"\*\*Doc source\*\*:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    raw_source = doc_source_match.group(1).strip() if doc_source_match else ""
    if raw_source:
        raw_source = raw_source.replace("\\\\\\\\", "/").strip().lstrip("/")
    entry["doc_source"] = raw_source

    tier_match = re.search(r"\*\*Doc source tier:\*\*\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    if not tier_match:
        tier_match = re.search(r"\*\*Doc source tier\*\*:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE)
    entry["doc_source_tier"] = tier_match.group(1).strip() if tier_match else ""

    snippet_match = re.search(
        r"\*\*Doc snippet:\*\*\s*(.*?)(?=\*\*Gate status:|\Z)", content, re.DOTALL | re.IGNORECASE
    )
    if not snippet_match:
        snippet_match = re.search(
            r"\*\*Doc snippet\*\*:\s*(.*?)(?=\*\*Gate status:|\Z)", content, re.DOTALL | re.IGNORECASE
        )
    entry["doc_snippet_claimed"] = snippet_match.group(1).strip() if snippet_match else ""

    return entry


def _split_flagged_sections(text: str) -> list:
    """flagged.md entries are separated by '\\n\\n---\\n\\n' (see main.py's
    persistence step); each section is itself a '## ...' mapping block
    with a trailing '**Gate status:** flagged: ...' line appended."""
    sections = [s.strip() for s in text.split("\n\n---\n\n") if s.strip()]
    return sections


def find_single_transcript(notes_dir: Path, thread_id: str | None) -> Path:
    if thread_id:
        path = notes_dir / f"transcript_{thread_id}.jsonl"
        if not path.exists():
            sys.exit(f"No transcript found at {path}")
        return path

    candidates = sorted(notes_dir.glob("transcript_*.jsonl"))
    if not candidates:
        sys.exit(
            f"No transcript_*.jsonl found under {notes_dir}. This script needs a "
            f"persisted transcript from a real agent run (see agents/tool_call_logger.py "
            f"save_calls()) -- it cannot fabricate grounding evidence."
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        sys.exit(
            f"Multiple transcripts found under {notes_dir}: {names}. "
            f"Pass --thread-id explicitly to disambiguate."
        )
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--thread-id", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would pass/fail without writing any files.",
    )
    args = parser.parse_args()

    project_dir = PROJECTS_DIR / args.project
    notes_dir = project_dir / "workspace" / "notes"
    mappings_dir = project_dir / "workspace" / "mappings"
    flagged_file = notes_dir / "flagged.md"

    if not flagged_file.exists():
        sys.exit(f"No flagged.md at {flagged_file} -- nothing to recheck.")

    transcript_path = find_single_transcript(notes_dir, args.thread_id)
    print(f"Using transcript: {transcript_path}")
    calls = load_calls(transcript_path)
    transcript = build_transcript_from_calls(calls, args.project, citation_validator)
    print(f"Loaded {len(calls)} raw tool calls -> {len(transcript.tool_calls)} registered sources.\n")

    freshness_res = freshness_check.check(project_dir)
    print(f"Project Freshness: {'PASSED' if freshness_res['passed'] else 'FAILED'}")
    if not freshness_res["passed"]:
        print(f"  Reason: {freshness_res['reason']}")

    sections = _split_flagged_sections(flagged_file.read_text(encoding="utf-8"))
    print(f"\nRechecking {len(sections)} entries from {flagged_file.name}...\n")

    now_passing = []
    still_flagged = []

    for raw_markdown in sections:
        parsed = _parse_markdown_mapping(raw_markdown)
        ref = parsed.get("repo_reference", "Unknown")

        struct_res = structural_check.check(parsed, project_dir)
        cite_res = citation_validator.check(parsed, transcript)

        failures = []
        if not freshness_res["passed"]:
            failures.append(f"Freshness Check Failed: {freshness_res['reason']}")
        if not struct_res["passed"]:
            failures.append(f"Structural Check Failed: {struct_res['reason']}")
        if not cite_res["passed"]:
            failures.append(f"Citation Check Failed: {cite_res['reason']}")

        if failures:
            reason_str = " | ".join(failures)
            print(f"  [STILL FLAGGED] {ref}\n       Reason: {reason_str}")
            content = re.sub(
                r"\*\*Gate status:\*\*\s*.*$",
                f"**Gate status:** flagged: {reason_str}",
                raw_markdown,
                flags=re.MULTILINE,
            )
            still_flagged.append(content)
        else:
            print(f"  [NOW PASSES] {ref}")
            content = re.sub(
                r"\*\*Gate status:\*\*\s*.*$", "**Gate status:** passed", raw_markdown, flags=re.MULTILINE
            )
            now_passing.append((ref, content))

    print(f"\n{len(now_passing)} of {len(sections)} entries now pass; {len(still_flagged)} still flagged.")

    if args.dry_run:
        print("\n--dry-run: no files written.")
        return

    mappings_dir.mkdir(parents=True, exist_ok=True)
    for ref, content in now_passing:
        ref_safe = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", ref)
        out_path = mappings_dir / f"{ref_safe}.md"
        out_path.write_text(content, encoding="utf-8")
        print(f"Wrote {out_path}")

    if still_flagged:
        flagged_file.write_text("\n\n---\n\n".join(still_flagged) + "\n", encoding="utf-8")
        print(f"Rewrote {flagged_file} with {len(still_flagged)} remaining entries.")
    else:
        flagged_file.unlink()
        print(f"All entries passed -- removed {flagged_file}.")


if __name__ == "__main__":
    main()
