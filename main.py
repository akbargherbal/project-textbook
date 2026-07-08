"""
main.py

Entry point. Loads a project's config.yaml, wires model provider,
permissions, subagents (local-first doc-grounder + repo-analyst), and the
orchestrator prompt into a create_deep_agent() instance.

Prerequisite: run scripts/fetch_sources.py --project <slug> first, so
framework_docs/ (and target_repo/, if git-sourced) exist on disk before
any agent session starts. This script does NOT fetch anything itself --
fetching is a separate, human-triggered, infrequent step.

Usage:
    export MODEL_PROVIDER=deepseek
    export DEEPSEEK_API_KEY=...
    python scripts/fetch_sources.py --project django-example
    python main.py --project django-example

NOTE: the exact create_deep_agent(...) signature should be re-verified
against docs.langchain.com/oss/python/deepagents before running this.
"""

import argparse
import sys
import re
from pathlib import Path

import yaml
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
import deepagents.backends.filesystem as db_filesystem
from langgraph.types import Command

# ----------------- Windows Path Compatibility Monkeypatch -----------------
# On Windows + Python 3.12+, .resolve() on nested paths can return extended
# paths prefixed with "\\?\". Because of this, full.relative_to(self.cwd) can
# fail when self.cwd does not have the prefix. We monkeypatch _resolve_path
# to normalize both paths before performing the relative check.
# --------------------------------------------------------------------------

_orig_resolve_path = FilesystemBackend._resolve_path
_raise_if_symlink_loop = getattr(
    db_filesystem, "_raise_if_symlink_loop", lambda x: None
)


def _patched_resolve_path(self, key: str) -> Path:
    if self.virtual_mode:
        vpath = key if key.startswith("/") else "/" + key
        if ".." in vpath or vpath.startswith("~"):
            msg = "Path traversal not allowed"
            raise ValueError(msg)
        full = (self.cwd / vpath.lstrip("/")).resolve()

        # Normalize paths for relative checking on Windows
        full_normalized = full
        cwd_normalized = self.cwd

        if sys.platform == "win32":
            full_str = str(full)
            if full_str.startswith("\\\\?\\"):
                full_normalized = Path(full_str[4:])
            cwd_str = str(self.cwd)
            if cwd_str.startswith("\\\\?\\"):
                cwd_normalized = Path(cwd_str[4:])

        try:
            full_normalized.relative_to(cwd_normalized)
        except ValueError:
            msg = f"Path:{full} outside root directory: {self.cwd}"
            raise ValueError(msg) from None

        _raise_if_symlink_loop(full)
        return full
    else:
        return _orig_resolve_path(self, key)


FilesystemBackend._resolve_path = _patched_resolve_path

from backends.model_provider import get_model
from config.permissions import PERMISSIONS
from agents.repo_analyst import REPO_ANALYST
from agents.doc_grounder import DOC_GROUNDER
from agents.orchestrator import build_orchestrator_prompt
from agents.scoped_tools import build_scoped_web_tools
from agents.tool_call_logger import ToolCallLogger, build_transcript
from gates.external_reference_scan import scan_and_log
from runtime.checkpointing import get_checkpointer, resolve_thread_id

# Import our verification gates
import gates.structural_check as structural_check
import gates.citation_validator as citation_validator
import gates.freshness_check as freshness_check

PROJECTS_DIR = Path(__file__).parent / "projects"


def load_project(project_slug: str) -> dict:
    config_path = PROJECTS_DIR / project_slug / "config.yaml"
    if not config_path.exists():
        print(
            f"No config.yaml at {config_path}. Copy "
            f"config/project.template.yaml there first.",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def parse_markdown_mapping(content: str) -> dict:
    """
    Parses a single AGENTS.md styled mapping entry from markdown content.
    """
    entry = {}

    # Extract repo_reference from header
    header_match = re.search(r"^##\s*(.+)$", content, re.MULTILINE)
    entry["repo_reference"] = header_match.group(1).strip() if header_match else ""

    # Extract Concept
    concept_match = re.search(
        r"\*\*Concept:\*\*\s*(.+)$", content, re.MULTILINE | re.IGNORECASE
    )
    if not concept_match:
        concept_match = re.search(
            r"\*\*Concept\*\*:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE
        )
    entry["concept"] = concept_match.group(1).strip() if concept_match else ""

    # Extract Doc source
    doc_source_match = re.search(
        r"\*\*Doc source:\*\*\s*(.+)$", content, re.MULTILINE | re.IGNORECASE
    )
    if not doc_source_match:
        doc_source_match = re.search(
            r"\*\*Doc source\*\*:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE
        )
    raw_source = doc_source_match.group(1).strip() if doc_source_match else ""

    # Normalize: a doubled-backslash run (4 literal backslash characters --
    # produced by some Windows-path serializations that escape "\\" as
    # "\\\\") collapses to a single forward slash. A lone single backslash
    # pair (2 literal backslash characters) is left untouched. Then strip
    # leading/trailing slashes.
    if raw_source:
        raw_source = raw_source.replace("\\\\\\\\", "/").strip().lstrip("/")
    entry["doc_source"] = raw_source

    # Extract Doc source tier
    tier_match = re.search(
        r"\*\*Doc source tier:\*\*\s*(.+)$", content, re.MULTILINE | re.IGNORECASE
    )
    if not tier_match:
        tier_match = re.search(
            r"\*\*Doc source tier\*\*:\s*(.+)$", content, re.MULTILINE | re.IGNORECASE
        )
    entry["doc_source_tier"] = tier_match.group(1).strip() if tier_match else ""

    # Extract Doc snippet (matches multiline text until Gate status or end of section)
    snippet_match = re.search(
        r"\*\*Doc snippet:\*\*\s*(.*?)(?=\*\*Gate status:|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if not snippet_match:
        snippet_match = re.search(
            r"\*\*Doc snippet\*\*:\s*(.*?)(?=\*\*Gate status:|\Z)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
    entry["doc_snippet_claimed"] = (
        snippet_match.group(1).strip() if snippet_match else ""
    )

    return entry


def parse_mappings_from_text(text: str) -> list[dict]:
    """
    Splits string content into separate markdown sections starting with '##'
    and parses each valid mapping entry.
    """
    entries = []
    raw_sections = re.split(r"^##\s+", text, flags=re.MULTILINE)

    for section in raw_sections:
        if not section.strip():
            continue
        full_section = "## " + section
        if "Concept:" in full_section or "Doc source:" in full_section:
            parsed = parse_markdown_mapping(full_section)
            if parsed.get("repo_reference") or parsed.get("concept"):
                entries.append({"raw_markdown": full_section, "parsed": parsed})
    return entries


def _prompt_for_decisions(action_requests: list[dict], review_configs: list[dict]) -> list[dict]:
    """
    Interactively collect one human decision per pending action_request, in
    the exact order LangGraph expects them back (see Command(resume=...)
    below). This is the "paused human-in-the-loop approval state" becoming
    a real prompt: the graph is genuinely suspended -- and checkpointed --
    while we wait on input() here, however long that takes.
    """
    config_by_tool = {cfg["action_name"]: cfg for cfg in review_configs}
    decisions = []
    print("\n--- Human approval required (see checkpoints.db for full history) ---")
    for action in action_requests:
        allowed = config_by_tool.get(action["name"], {}).get(
            "allowed_decisions", ["approve", "reject"]
        )
        print(f"\nTool: {action['name']}")
        print(f"Args: {action['args']}")
        choice = ""
        while choice not in allowed:
            choice = input(f"Decision [{'/'.join(allowed)}]: ").strip().lower()
        decisions.append({"type": choice})
    return decisions


def _run_until_settled(agent, config: dict, initial_input=None):
    """
    Invoke (or resume) the agent and keep resuming through every paused
    human-in-the-loop interrupt until the graph actually finishes.

    `initial_input` is either the first user message (new session) or None
    (resuming a thread that was left mid-run -- e.g. the process was killed
    -- with no interrupt of its own to answer; LangGraph continues from the
    thread's last checkpoint in that case).
    """
    result = agent.invoke(initial_input, config=config, version="v2")

    while result.interrupts:
        interrupt_value = result.interrupts[0].value
        decisions = _prompt_for_decisions(
            interrupt_value["action_requests"], interrupt_value["review_configs"]
        )
        result = agent.invoke(
            Command(resume={"decisions": decisions}), config=config, version="v2"
        )

    return result.value


def run(
    project_slug: str,
    task_description: str,
    thread_id: str | None = None,
    resume: bool = False,
):
    project_dir = PROJECTS_DIR / project_slug
    project_config = load_project(project_slug)
    framework_name = project_config.get("framework_name", project_slug)

    for required_dir, label in [
        (project_dir / "target_repo", "target_repo/"),
        (project_dir / "framework_docs", "framework_docs/"),
    ]:
        if not required_dir.exists() or not any(required_dir.iterdir()):
            print(
                f"{label} is empty for project '{project_slug}'. Run "
                f"scripts/fetch_sources.py --project {project_slug} first, "
                f"or populate it manually if source: local.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Static, one-time-per-fetch scan of framework_docs/ for outbound
    # references. Not part of the agent loop -- run here so it's fresh
    # for this session's review, but it doesn't depend on anything the
    # agent does this run.
    scan_and_log(project_dir)

    model = get_model()

    web_search_scoped, web_fetch_scoped = build_scoped_web_tools(project_config)
    fallback_enabled = project_config.get("fallback", {}).get("enabled", False)

    # Note: Built-in filesystem tools ('ls', 'read_file', 'glob', 'grep')
    # are automatically injected by deepagents's FilesystemMiddleware.
    # We only specify custom compiled LangChain tools here.
    doc_grounder_with_tools = {
        **DOC_GROUNDER,
        "tools": [web_search_scoped, web_fetch_scoped] if fallback_enabled else [],
    }

    repo_analyst_with_tools = {
        **REPO_ANALYST,
        "tools": [],
    }

    orchestrator_prompt = build_orchestrator_prompt(project_slug, framework_name)

    # Instantiate FilesystemBackend so virtual filesystem tools map to real disks
    real_filesystem_backend = FilesystemBackend(root_dir=".", virtual_mode=True)

    # --- Persistent checkpointing (checkpoints.db at the project root) ---
    # Required for: (a) recording full execution history and subagent (task
    # tool) decisions as they happen, (b) pausing on a human-in-the-loop
    # approval below, and (c) resuming this exact thread later via
    # --resume / --thread-id, whether that "later" is a fresh CLI process
    # or a retry after a crash. See runtime/checkpointing.py.
    checkpointer = get_checkpointer()
    resolved_thread_id, is_resuming = resolve_thread_id(
        project_dir, project_slug, thread_id, resume
    )

    agent = create_deep_agent(
        model=model,
        tools=[],
        system_prompt=orchestrator_prompt,
        permissions=PERMISSIONS,
        subagents=[repo_analyst_with_tools, doc_grounder_with_tools],
        backend=real_filesystem_backend,
        checkpointer=checkpointer,
        # Pause for human approval before every write_file call -- this is
        # the point at which the orchestrator commits a mapping entry to
        # workspace/mappings/ (step 5 of agents/orchestrator.py's plan).
        # "edit" lets a reviewer fix up content inline instead of only
        # approve/reject; the entry still passes back through the gates in
        # this file afterward regardless of the decision made here.
        # interrupt_on was previously omitted -- see LIMITATIONS.md; this
        # is that gap being filled in.
        interrupt_on={
            "write_file": {"allowed_decisions": ["approve", "edit", "reject"]},
        },
    )

    print(f"Project: {project_slug} ({framework_name})")
    print(
        f"Fallback web access: {'enabled' if fallback_enabled else 'DISABLED -- local docs only'}"
    )
    print(f"Thread: {resolved_thread_id}{' (resuming)' if is_resuming else ' (new session)'}")

    # config is keyed by thread_id -- this is what ties this invocation to
    # a specific row of checkpoint history in checkpoints.db, and what a
    # later `--resume --thread-id {resolved_thread_id}` looks up.
    tool_logger = ToolCallLogger()
    run_config = {
        "callbacks": [tool_logger],
        "configurable": {"thread_id": resolved_thread_id},
    }

    if is_resuming:
        print("Resuming paused/interrupted session -- no new task given.\n")
        # No new user message: continue from wherever this thread's last
        # checkpoint left off. If it was paused on a HITL interrupt,
        # the state.tasks lookup below surfaces that immediately; if the
        # process was merely killed mid-run with no interrupt pending,
        # LangGraph resumes execution on its own from the last completed
        # checkpoint.
        pending_state = agent.get_state(run_config)
        if pending_state.tasks and any(
            getattr(t, "interrupts", None) for t in pending_state.tasks
        ):
            interrupt_value = pending_state.tasks[0].interrupts[0].value
            decisions = _prompt_for_decisions(
                interrupt_value["action_requests"], interrupt_value["review_configs"]
            )
            values = _run_until_settled(
                agent,
                run_config,
                initial_input=Command(resume={"decisions": decisions}),
            )
        elif pending_state.next:
            values = _run_until_settled(agent, run_config, initial_input=None)
        else:
            print(
                "No paused work found for this thread -- it already ran to "
                "completion. Starting a new task on the same thread instead.\n"
            )
            print(f"Task: {task_description}\n")
            values = _run_until_settled(
                agent,
                run_config,
                initial_input={
                    "messages": [{"role": "user", "content": task_description}]
                },
            )
    else:
        print(f"Task: {task_description}\n")
        values = _run_until_settled(
            agent,
            run_config,
            initial_input={
                "messages": [{"role": "user", "content": task_description}]
            },
        )

    # NOTE: transcript is built from a callback logger (below), not from
    # result["messages"]. Subagents (doc-grounder, repo-analyst) run as
    # isolated sub-invocations via the `task` tool -- their internal
    # read_file/grep/web_fetch calls never appear in the top-level
    # result["messages"], only their final text summary does. Reconstructing
    # from messages alone made every citation look fabricated even when the
    # subagent genuinely read the file. Callbacks propagate through the full
    # run tree (including subagent sub-invocations), so they're the correct
    # source of truth here -- see agents/tool_call_logger.py.
    result = values

    print("\n--- Gate results ---")

    # 1. Build SessionTranscript from the callback-captured tool-call log
    transcript = build_transcript(tool_logger, project_slug, citation_validator)

    # 2. Gather Proposed Mapping Entries from Workspace or AI Output
    mappings_dir = project_dir / "workspace" / "mappings"
    flagged_file = project_dir / "workspace" / "notes" / "flagged.md"
    mappings_dir.mkdir(parents=True, exist_ok=True)
    flagged_file.parent.mkdir(parents=True, exist_ok=True)

    all_proposed_entries = []
    mapping_files = list(mappings_dir.glob("**/*.md"))

    # Read from filesystem
    for file_path in mapping_files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            parsed_sections = parse_mappings_from_text(content)
            for item in parsed_sections:
                all_proposed_entries.append(
                    {
                        "file_path": file_path,
                        "raw_markdown": item["raw_markdown"],
                        "parsed": item["parsed"],
                    }
                )
        except Exception as e:
            print(f"Error reading mapping file {file_path}: {e}")

    # Fallback/Supplemental: Scan final Assistant message if nothing was saved on disk
    ai_messages = [
        m
        for m in result["messages"]
        if getattr(m, "role", None) == "assistant"
        or type(m).__name__ == "AIMessage"
        or (isinstance(m, dict) and m.get("role") == "assistant")
    ]
    if ai_messages:
        for msg in ai_messages[-2:]:
            msg_content = (
                msg.get("content", "")
                if isinstance(msg, dict)
                else getattr(msg, "content", "")
            )
            if isinstance(msg_content, str) and msg_content:
                parsed_sections = parse_mappings_from_text(msg_content)
                for item in parsed_sections:
                    ref_safe = re.sub(
                        r"[^a-zA-Z0-9_\-\.]",
                        "_",
                        item["parsed"].get("repo_reference", "mapping"),
                    )
                    file_path = mappings_dir / f"{ref_safe}.md"
                    # Add if not already parsed from disk
                    if not any(
                        entry["parsed"].get("repo_reference")
                        == item["parsed"].get("repo_reference")
                        for entry in all_proposed_entries
                    ):
                        all_proposed_entries.append(
                            {
                                "file_path": file_path,
                                "raw_markdown": item["raw_markdown"],
                                "parsed": item["parsed"],
                            }
                        )

    # 3. Perform Gate Checks (Freshness, Structural, and Citation)
    freshness_res = freshness_check.check(project_dir)

    passed_entries = []
    flagged_entries = []
    files_to_delete = set()
    files_to_write = {}

    for entry_info in all_proposed_entries:
        file_path = entry_info["file_path"]
        raw_markdown = entry_info["raw_markdown"]
        parsed_entry = entry_info["parsed"]

        struct_res = structural_check.check(parsed_entry, project_dir)
        cite_res = citation_validator.check(parsed_entry, transcript)

        failures = []
        if not freshness_res["passed"]:
            failures.append(f"Freshness Check Failed: {freshness_res['reason']}")
        if not struct_res["passed"]:
            failures.append(f"Structural Check Failed: {struct_res['reason']}")
        if not cite_res["passed"]:
            failures.append(f"Citation Check Failed: {cite_res['reason']}")

        if failures:
            reason_str = " | ".join(failures)
            flagged_content = raw_markdown
            if "**Gate status:**" in flagged_content:
                flagged_content = re.sub(
                    r"\*\*Gate status:\*\*\s*.*$",
                    f"**Gate status:** flagged: {reason_str}",
                    flagged_content,
                    flags=re.MULTILINE,
                )
            else:
                flagged_content += f"\n**Gate status:** flagged: {reason_str}"

            flagged_entries.append(
                {
                    "entry": parsed_entry,
                    "content": flagged_content,
                    "reason": reason_str,
                }
            )
            files_to_delete.add(file_path)
        else:
            passed_content = raw_markdown
            if "**Gate status:**" in passed_content:
                passed_content = re.sub(
                    r"\*\*Gate status:\*\*\s*.*$",
                    "**Gate status:** passed",
                    passed_content,
                    flags=re.MULTILINE,
                )
            else:
                passed_content += "\n**Gate status:** passed"

            passed_entries.append({"entry": parsed_entry, "content": passed_content})
            files_to_write[file_path] = passed_content

    # 4. Persistence Adjustments
    for fp in files_to_delete:
        if fp.exists():
            try:
                fp.unlink()
            except Exception as e:
                print(f"Error removing failed mapping file {fp}: {e}")

    for fp, content in files_to_write.items():
        try:
            fp.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"Error writing passed mapping file {fp}: {e}")

    if flagged_entries:
        try:
            existing_flagged = ""
            if flagged_file.exists():
                existing_flagged = flagged_file.read_text(
                    encoding="utf-8", errors="replace"
                )

            new_flagged_blocks = []
            for item in flagged_entries:
                if item["content"].strip()[:100] not in existing_flagged:
                    new_flagged_blocks.append(item["content"])

            if new_flagged_blocks:
                separator = "\n\n---\n\n"
                with open(flagged_file, "a", encoding="utf-8") as f:
                    if existing_flagged and not existing_flagged.endswith("\n\n"):
                        f.write("\n\n")
                    f.write(separator.join(new_flagged_blocks) + "\n")
        except Exception as e:
            print(f"Error writing to flagged.md: {e}")

    # 5. Output Verification Summaries to Console
    print(f"Project Freshness: {'PASSED' if freshness_res['passed'] else 'FAILED'}")
    if not freshness_res["passed"]:
        print(f"  Reason: {freshness_res['reason']}")
    print(f"Processed {len(all_proposed_entries)} proposed mapping entry/entries:")
    print(f"  - Passed structural/citation/freshness gates: {len(passed_entries)}")
    print(f"  - Flagged by validation gates: {len(flagged_entries)}")

    if passed_entries:
        print("\nVerified Mappings:")
        for idx, p in enumerate(passed_entries, 1):
            ref = p["entry"].get("repo_reference", "Unknown")
            concept = p["entry"].get("concept", "Unknown")
            print(f"  {idx}. [PASSED] {ref} -> {concept}")

    if flagged_entries:
        print("\nFlagged Mappings (Details written to workspace/notes/flagged.md):")
        for idx, f in enumerate(flagged_entries, 1):
            ref = f["entry"].get("repo_reference", "Unknown")
            reason = f["reason"]
            print(f"  {idx}. [FLAGGED] {ref}\n       Reason: {reason}")

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        required=True,
        help="Project slug under projects/ (matches its config.yaml)",
    )
    parser.add_argument(
        "--task",
        default=(
            "Investigate target_repo/ and produce a code-to-documentation "
            "mapping for the concepts it uses. Follow AGENTS.md house style."
        ),
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help=(
            "Thread ID for this session's checkpoint history in "
            "checkpoints.db. Omit to auto-generate a new one (recorded as "
            "this project's 'last thread' for a future --resume)."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume a previously paused/interrupted session instead of "
            "starting a new task. Uses --thread-id if given, otherwise the "
            "last thread_id recorded for --project."
        ),
    )
    args = parser.parse_args()
    run(args.project, args.task, thread_id=args.thread_id, resume=args.resume)


if __name__ == "__main__":
    main()
