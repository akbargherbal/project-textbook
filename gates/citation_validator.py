"""
gates/citation_validator.py

Grounding/Truth axis. Diffs a mapping entry's claimed citation against the
ACTUAL tool-call transcript for the session -- regardless of whether the
citation came from a local framework_docs/ read (primary path) or a
fallback web fetch (secondary path). Same rule either way: if it's not in
the transcript, it wasn't actually grounded, no matter how plausible it
sounds.

This does NOT ask an LLM whether a citation "looks right." It's a
transcript diff. Lives in gates/ -- write/execute-denied to the agent.
"""
from dataclasses import dataclass, field


@dataclass
class ToolCallRecord:
    tool_name: str          # "read_file" | "web_fetch_scoped" | "web_search_scoped"
    source: str              # local file path OR URL
    retrieved_content: str
    timestamp: str


@dataclass
class SessionTranscript:
    """Populate this from the actual deepagents run's tool-call log."""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    def was_retrieved(self, source: str) -> ToolCallRecord | None:
        for record in self.tool_calls:
            if record.tool_name in ("read_file", "web_fetch_scoped", "web_search_scoped") \
                    and record.source == source:
                return record
        return None


def check(mapping_entry: dict, transcript: SessionTranscript) -> dict:
    """
    mapping_entry expected shape:
      {
        "doc_source": "framework_docs/topics/auth/default.txt"  # or a URL
                        "https://docs.djangoproject.com/...",
        "doc_source_tier": "local" | "fallback",
        "doc_snippet_claimed": "...",
        ...
      }

    Returns {"passed": bool, "reason": str}
    """
    source = mapping_entry.get("doc_source")
    tier = mapping_entry.get("doc_source_tier", "unknown")
    claimed_snippet = mapping_entry.get("doc_snippet_claimed", "")

    if not source:
        return {"passed": False, "reason": "No doc_source on this mapping entry -- ungrounded claim."}

    record = transcript.was_retrieved(source)
    if record is None:
        return {
            "passed": False,
            "reason": (
                f"FABRICATED CITATION ({tier}): {source} was never actually "
                f"read/fetched this session. Route to human review, do not "
                f"auto-correct by generating a replacement citation."
            ),
        }

    if claimed_snippet.strip() and claimed_snippet.strip()[:40] not in record.retrieved_content:
        return {
            "passed": False,
            "reason": (
                f"Source ({tier}) was retrieved, but the claimed snippet does "
                f"not appear in what was actually read from {source}. Possible "
                f"paraphrase drift or misattribution -- route to human review."
            ),
        }

    return {"passed": True, "reason": f"Citation verified against transcript ({tier}): {source}"}
