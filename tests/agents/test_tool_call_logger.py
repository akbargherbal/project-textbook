"""
tests/agents/test_tool_call_logger.py

Pure bookkeeping -- no LangChain runtime needed, only the
BaseCallbackHandler interface shape. Call on_tool_start / on_tool_end
directly with hand-built args.
"""

import pytest

from agents.tool_call_logger import ToolCallLogger, build_transcript
import gates.citation_validator as citation_validator

pytestmark = pytest.mark.unit


def test_on_tool_start_with_explicit_inputs_records_call():
    logger = ToolCallLogger()
    logger.on_tool_start(
        {"name": "read_file"}, "{}", run_id="r1", inputs={"file_path": "a.txt"}
    )
    assert len(logger.calls) == 1
    assert logger.calls[0]["name"] == "read_file"
    assert logger.calls[0]["inputs"] == {"file_path": "a.txt"}
    assert logger.calls[0]["output"] is None


def test_on_tool_start_parses_valid_json_input_str():
    logger = ToolCallLogger()
    logger.on_tool_start({"name": "read_file"}, '{"file_path": "a.txt"}', run_id="r1")
    assert logger.calls[0]["inputs"] == {"file_path": "a.txt"}


def test_on_tool_start_falls_back_to_raw_on_invalid_json():
    logger = ToolCallLogger()
    logger.on_tool_start({"name": "read_file"}, "not valid json{{{", run_id="r1")
    assert logger.calls[0]["inputs"] == {"__raw__": "not valid json{{{"}


def test_on_tool_end_attaches_output_to_matching_run_id():
    logger = ToolCallLogger()
    logger.on_tool_start(
        {"name": "read_file"}, "{}", run_id="r1", inputs={"file_path": "a.txt"}
    )
    logger.on_tool_end("file content here", run_id="r1")
    assert logger.calls[0]["output"] == "file content here"


def test_on_tool_end_with_unknown_run_id_does_not_raise():
    logger = ToolCallLogger()
    logger.on_tool_start(
        {"name": "read_file"}, "{}", run_id="r1", inputs={"file_path": "a.txt"}
    )
    # Should not raise even though "unknown-run-id" was never registered.
    logger.on_tool_end("some output", run_id="unknown-run-id")
    assert logger.calls[0]["output"] is None


def test_serialized_as_object_with_name_attr():
    logger = ToolCallLogger()

    class FakeSerialized:
        name = "read_file"

    logger.on_tool_start(
        FakeSerialized(), "{}", run_id="r1", inputs={"file_path": "a.txt"}
    )
    assert logger.calls[0]["name"] == "read_file"


# --- build_transcript -------------------------------------------------


def _logger_with_calls(*calls):
    logger = ToolCallLogger()
    logger.calls = list(calls)
    return logger


def test_read_file_registers_both_raw_and_project_relative_path():
    logger = _logger_with_calls(
        {
            "name": "read_file",
            "inputs": {"file_path": "projects/demo/framework_docs/x.txt"},
            "output": "the actual content",
        }
    )
    transcript = build_transcript(logger, "demo", citation_validator)
    sources = {r.source for r in transcript.tool_calls}
    assert "projects/demo/framework_docs/x.txt" in sources
    assert "framework_docs/x.txt" in sources
    for r in transcript.tool_calls:
        assert r.tool_name == "read_file"
        assert r.retrieved_content == "the actual content"


@pytest.mark.parametrize("project_slug", ["demo-project"])
def test_read_file_bare_relative_path_gets_project_relative_source(project_slug):
    logger = _logger_with_calls(
        {
            "name": "read_file",
            "inputs": {"file_path": "framework_docs/x.txt"},
            "output": "content",
        }
    )
    transcript = build_transcript(logger, project_slug, citation_validator)
    sources = {r.source for r in transcript.tool_calls}
    assert "framework_docs/x.txt" in sources
    assert f"projects/{project_slug}/framework_docs/x.txt" in sources


def test_web_search_maps_to_web_search_scoped():
    logger = _logger_with_calls(
        {
            "name": "web_search",
            "inputs": {"query": "some query"},
            "output": "results",
        }
    )
    transcript = build_transcript(logger, "demo", citation_validator)
    assert len(transcript.tool_calls) == 1
    assert transcript.tool_calls[0].tool_name == "web_search_scoped"
    assert transcript.tool_calls[0].source == "some query"


def test_web_fetch_maps_to_web_fetch_scoped():
    logger = _logger_with_calls(
        {
            "name": "web_fetch",
            "inputs": {"url": "https://example.com/page"},
            "output": "fetched content",
        }
    )
    transcript = build_transcript(logger, "demo", citation_validator)
    assert len(transcript.tool_calls) == 1
    assert transcript.tool_calls[0].tool_name == "web_fetch_scoped"
    assert transcript.tool_calls[0].source == "https://example.com/page"


def test_unrecognized_tool_name_is_silently_skipped():
    logger = _logger_with_calls(
        {
            "name": "ls",
            "inputs": {"path": "/"},
            "output": "a.txt\nb.txt",
        }
    )
    transcript = build_transcript(logger, "demo", citation_validator)
    assert transcript.tool_calls == []


def test_call_with_empty_resolved_source_is_skipped():
    logger = _logger_with_calls(
        {
            "name": "read_file",
            "inputs": {"file_path": ""},
            "output": "content",
        }
    )
    transcript = build_transcript(logger, "demo", citation_validator)
    assert transcript.tool_calls == []


def test_grep_is_also_mapped_to_read_file():
    logger = _logger_with_calls(
        {
            "name": "grep",
            "inputs": {"file_path": "framework_docs/x.txt"},
            "output": "matched lines",
        }
    )
    transcript = build_transcript(logger, "demo", citation_validator)
    tool_names = {r.tool_name for r in transcript.tool_calls}
    assert tool_names == {"read_file"}
