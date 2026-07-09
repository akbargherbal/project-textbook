"""
agents/tool_call_logger.py

Callback-based tool-call transcript logger.

WHY THIS EXISTS:
main.py used to reconstruct the citation-validator's SessionTranscript by
walking `result["messages"]` after `agent.invoke(...)` returned. That only
captures the TOP-LEVEL orchestrator's messages. Subagents (doc-grounder,
repo-analyst) are invoked via the `task` tool and run as isolated
sub-invocations -- their internal read_file/grep/web_fetch calls never get
flattened into the parent's `result["messages"]`. The top level only ever
sees the subagent's final text summary. Net effect: every citation looked
"fabricated" even when the subagent genuinely read the file, because the
transcript used to check it was built from the wrong data.

LangChain callbacks fire for every tool invocation in the run tree
regardless of nesting depth (on_tool_start/on_tool_end propagate up through
parent_run_id chains even across sub-graph/subagent boundaries), so this
is the correct source of truth for "what was actually retrieved this
session" -- matching what citation_validator.py's docstring always assumed
("the actual deepagents run's tool-call log").
"""
import json
from langchain_core.callbacks import BaseCallbackHandler


class ToolCallLogger(BaseCallbackHandler):
    """Pass an instance of this via config={"callbacks": [...]} to
    agent.invoke(...). After the run, .calls holds every tool invocation
    that happened anywhere in the run tree, in order."""

    def __init__(self):
        self.calls = []  # list of dicts: {name, inputs, output}
        self._by_run_id = {}

    def on_tool_start(self, serialized, input_str, *, run_id=None, inputs=None, **kwargs):
        name = None
        if isinstance(serialized, dict):
            name = serialized.get("name")
        else:
            name = getattr(serialized, "name", None)

        parsed_inputs = inputs
        if parsed_inputs is None:
            # Older langchain-core only gives input_str; try to recover a dict.
            try:
                parsed_inputs = json.loads(input_str)
            except (TypeError, ValueError):
                parsed_inputs = {"__raw__": input_str}

        record = {"name": name, "inputs": parsed_inputs, "output": None}
        self.calls.append(record)
        if run_id is not None:
            self._by_run_id[str(run_id)] = record

    def on_tool_end(self, output, *, run_id=None, **kwargs):
        if run_id is not None:
            record = self._by_run_id.get(str(run_id))
            if record is not None:
                record["output"] = output


def save_calls(logger: "ToolCallLogger", path) -> None:
    """
    Persist a ToolCallLogger's raw .calls to a JSONL file, one call per
    line, so a session's "what was actually retrieved" record survives
    past the lifetime of the process that produced it.

    WHY THIS EXISTS:
    citation_validator.check() only ever had a live SessionTranscript to
    check against -- built in-memory, for the duration of one
    agent.invoke() call, and thrown away when the process exited. If that
    process crashed, got resumed, or simply finished, there was no way to
    re-validate a flagged citation without re-running the LLM from
    scratch, even though the actual grounding evidence (the tool call and
    its result) genuinely happened and was never in question. This
    persists that evidence so gate-checking can be re-run standalone,
    offline, with no model/API calls at all -- the citation check becomes
    a replayable diff against a real record instead of a one-shot check
    against ephemeral memory.

    `output` fields are serialized with `default=str` since tool outputs
    are not guaranteed to be JSON-native (e.g. LangChain message/content
    objects) -- this matches build_transcript()'s existing str(content)
    handling below, so replaying a saved transcript produces identical
    SessionTranscript records to using the logger live.
    """
    import json as _json

    path = str(path)
    with open(path, "w", encoding="utf-8") as f:
        for call in logger.calls:
            f.write(_json.dumps(call, default=str) + "\n")


def load_calls(path) -> list:
    """
    Inverse of save_calls(): read a persisted transcript JSONL back into
    the same list-of-dicts shape ToolCallLogger.calls has, suitable for
    passing straight into build_transcript_from_calls().
    """
    import json as _json

    path = str(path)
    calls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                calls.append(_json.loads(line))
    return calls


def build_transcript_from_calls(calls: list, project_slug: str, citation_validator):
    """
    Same transform as build_transcript(), but takes a plain list of call
    dicts (e.g. from load_calls()) instead of a live ToolCallLogger. This
    is the function a standalone, offline gate-recheck should call --
    build_transcript() below is now a thin wrapper around this for the
    live-logger case, so both paths share one normalization
    implementation and can't silently drift apart.
    """
    import re

    transcript = citation_validator.SessionTranscript()

    for call in calls:
        name = call["name"]
        args = call["inputs"] or {}
        content = call["output"]

        mapped_name = None
        if name in ("read_file", "grep"):
            mapped_name = "read_file"
        elif name in ("web_fetch", "web_fetch_scoped"):
            mapped_name = "web_fetch_scoped"
        elif name in ("web_search", "web_search_scoped"):
            mapped_name = "web_search_scoped"

        if not mapped_name:
            continue

        if mapped_name == "read_file":
            source = (
                args.get("file_path")
                or args.get("path")
                or args.get("filepath")
                or args.get("file")
                or ""
            )
        else:
            source = args.get("url") or args.get("query") or ""

        if not source:
            continue

        sources_to_register = [str(source)]
        if mapped_name == "read_file" and isinstance(source, str):
            normalized_source = source.replace("\\", "/").lstrip("/")
            sources_to_register.append(normalized_source)

            match = re.match(r"^projects/[^/]+/(.+)$", normalized_source)
            if match:
                sources_to_register.append(match.group(1))
            elif (
                not normalized_source.startswith("projects/")
                and not normalized_source.startswith("/")
                and ":" not in normalized_source
            ):
                sources_to_register.append(f"projects/{project_slug}/{normalized_source}")

        for s in set(sources_to_register):
            record = citation_validator.ToolCallRecord(
                tool_name=mapped_name,
                source=s,
                retrieved_content=str(content),
                timestamp="0",
            )
            transcript.tool_calls.append(record)

    return transcript


def build_transcript(logger: "ToolCallLogger", project_slug: str, citation_validator):
    """
    Convert a live ToolCallLogger's captured calls into a
    citation_validator.SessionTranscript. Kept as the original entry
    point so existing call sites (main.py) don't need to change -- this
    is now a thin wrapper over build_transcript_from_calls() so the
    live-logger path and the reload-from-disk path (see load_calls())
    share one normalization implementation.
    """
    return build_transcript_from_calls(logger.calls, project_slug, citation_validator)
