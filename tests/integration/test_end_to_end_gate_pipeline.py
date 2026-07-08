"""
tests/integration/test_end_to_end_gate_pipeline.py

Exercises real gates (structural_check, citation_validator,
freshness_check), real parsing (parse_markdown_mapping /
parse_mappings_from_text), and the real agents/tool_call_logger.py
build_transcript() together -- no mocking of gates themselves. Only the
deepagents/model boundary in main.py is mocked (via the standard
test_main_run.py pattern), OR, for the narrower tests in this file, the
gate + parsing + transcript wiring is exercised directly without going
through main.run() at all, to keep these tests fast and focused on the
gate pipeline itself rather than agent orchestration.
"""

from pathlib import Path

import pytest
import yaml

import gates.citation_validator as citation_validator
import gates.freshness_check as freshness_check
import gates.structural_check as structural_check
from agents.tool_call_logger import ToolCallLogger, build_transcript
import main

pytestmark = pytest.mark.integration


def _write_project_config(project_dir, **overrides):
    cfg = {
        "project_name": "demo-project",
        "framework_name": "Django",
        "target_repo": {"source": "local"},
        "framework_docs": {"source": "local", "ref": "stable/5.1.x"},
        "fallback": {"enabled": True, "allowed_domains": ["docs.djangoproject.com"]},
        "external_reference_policy": "flag",
    }
    cfg.update(overrides)
    (project_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    return cfg


def test_full_pipeline_real_agent_read_produces_verified_citation(project_dir):
    """Simulates a real deepagents run: a callback logger captures a
    read_file tool call made by a subagent, build_transcript() converts
    it into a SessionTranscript, and citation_validator + structural_check
    + freshness_check all run against real on-disk fixtures -- proving
    the whole chain (callback -> transcript -> gates) works together,
    not just each piece in isolation."""
    _write_project_config(
        project_dir, framework_docs={"source": "local", "ref": "stable/5.1.x"}
    )
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    (project_dir / "target_repo" / "requirements.txt").write_text("Django==5.1.4\n")
    (project_dir / "framework_docs" / "topics").mkdir()
    doc_content = "A field is used to store data on a model."
    (project_dir / "framework_docs" / "topics" / "models.txt").write_text(doc_content)

    # Simulate a subagent's read_file callback firing during a real run.
    logger = ToolCallLogger()
    logger.on_tool_start(
        {"name": "read_file"},
        input_str=None,
        run_id="run-1",
        inputs={"file_path": "projects/demo-project/framework_docs/topics/models.txt"},
    )
    logger.on_tool_end(doc_content, run_id="run-1")

    transcript = build_transcript(logger, "demo-project", citation_validator)

    mapping_entry = {
        "repo_reference": "app.py:1",
        "concept": "assignment",
        "doc_source": "framework_docs/topics/models.txt",
        "doc_source_tier": "local",
        "doc_snippet_claimed": "A field is used to store data",
    }

    struct_res = structural_check.check(mapping_entry, project_dir)
    cite_res = citation_validator.check(mapping_entry, transcript)
    fresh_res = freshness_check.check(project_dir)

    assert struct_res["passed"] is True
    assert cite_res["passed"] is True
    assert fresh_res["passed"] is True


def test_full_pipeline_fabricated_citation_is_caught_end_to_end(project_dir):
    """The transcript never saw this source read -- even though the
    structural reference is real, citation_validator must still flag it
    as fabricated."""
    _write_project_config(
        project_dir, framework_docs={"source": "local", "ref": "stable/5.1.x"}
    )
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")

    # No tool calls at all -- nothing was actually read this session.
    logger = ToolCallLogger()
    transcript = build_transcript(logger, "demo-project", citation_validator)

    mapping_entry = {
        "repo_reference": "app.py:1",
        "concept": "assignment",
        "doc_source": "framework_docs/topics/models.txt",
        "doc_source_tier": "local",
        "doc_snippet_claimed": "A field is used to store data",
    }

    struct_res = structural_check.check(mapping_entry, project_dir)
    cite_res = citation_validator.check(mapping_entry, transcript)

    assert struct_res["passed"] is True
    assert cite_res["passed"] is False
    assert "FABRICATED CITATION" in cite_res["reason"]


def test_full_pipeline_subagent_web_fetch_is_visible_via_callback(project_dir):
    """Regression test for the exact bug agents/tool_call_logger.py's
    docstring describes: a subagent's internal web_fetch call (via the
    task tool) must be visible to citation_validator through the
    callback-based transcript, even though it would never have appeared
    in a top-level result['messages'] walk."""
    _write_project_config(
        project_dir,
        framework_docs={"source": "local", "ref": "stable/5.1.x"},
        fallback={"enabled": True, "allowed_domains": ["docs.djangoproject.com"]},
    )
    (project_dir / "target_repo" / "views.py").write_text("def view(): pass\n")

    fetched_content = "LoginRequiredMixin restricts view access to authenticated users."
    logger = ToolCallLogger()
    logger.on_tool_start(
        {"name": "web_fetch"},
        input_str=None,
        run_id="sub-run-1",
        inputs={"url": "https://docs.djangoproject.com/topics/auth/"},
    )
    logger.on_tool_end(fetched_content, run_id="sub-run-1")

    transcript = build_transcript(logger, "demo-project", citation_validator)

    mapping_entry = {
        "repo_reference": "views.py:1",
        "concept": "LoginRequiredMixin",
        "doc_source": "https://docs.djangoproject.com/topics/auth/",
        "doc_source_tier": "fallback",
        "doc_snippet_claimed": "LoginRequiredMixin restricts view access",
    }

    struct_res = structural_check.check(mapping_entry, project_dir)
    cite_res = citation_validator.check(mapping_entry, transcript)

    assert struct_res["passed"] is True
    assert cite_res["passed"] is True


def test_full_pipeline_parsed_markdown_flows_through_all_three_gates(project_dir):
    """Exercises parse_markdown_mapping -> all three gates in sequence,
    using main.py's own parser rather than hand-built dicts, to confirm
    the parser's output shape is exactly what the gates expect."""
    _write_project_config(
        project_dir, framework_docs={"source": "local", "ref": "stable/5.1.x"}
    )
    (project_dir / "target_repo" / "app.py").write_text("line1\nline2\nline3\n")
    (project_dir / "target_repo" / "requirements.txt").write_text("Django==5.1.4\n")
    (project_dir / "framework_docs" / "topics").mkdir()
    doc_content = "A field is used to store data on a model."
    (project_dir / "framework_docs" / "topics" / "models.txt").write_text(doc_content)

    raw_markdown = (
        "## app.py:2\n"
        "**Concept:** assignment\n"
        "**Doc source:** framework_docs/topics/models.txt\n"
        "**Doc source tier:** local\n"
        "**Doc snippet:** A field is used to store data\n"
    )
    parsed = main.parse_markdown_mapping(raw_markdown)

    logger = ToolCallLogger()
    logger.on_tool_start(
        {"name": "read_file"},
        input_str=None,
        run_id="run-1",
        inputs={"file_path": "projects/demo-project/framework_docs/topics/models.txt"},
    )
    logger.on_tool_end(doc_content, run_id="run-1")
    transcript = build_transcript(logger, "demo-project", citation_validator)

    assert structural_check.check(parsed, project_dir)["passed"] is True
    assert citation_validator.check(parsed, transcript)["passed"] is True
    assert freshness_check.check(project_dir)["passed"] is True
