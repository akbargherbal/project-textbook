"""
tests/gates/test_citation_validator.py

Highest-stakes gate (fabrication + metric-gaming detection). Every branch
of check() is tested independently using SessionTranscript/ToolCallRecord
directly -- not via agents/tool_call_logger.py (that's its own unit,
tests/agents/test_tool_call_logger.py).
"""

import pytest

from gates import citation_validator
from gates.citation_validator import SessionTranscript, ToolCallRecord

pytestmark = pytest.mark.unit


def _transcript(*records):
    return SessionTranscript(tool_calls=list(records))


def test_no_doc_source_fails_ungrounded(make_mapping_entry):
    entry = make_mapping_entry(doc_source=None)
    result = citation_validator.check(entry, _transcript())
    assert result["passed"] is False
    assert "ungrounded" in result["reason"]


def test_doc_source_missing_key_fails_ungrounded():
    result = citation_validator.check({}, _transcript())
    assert result["passed"] is False
    assert "ungrounded" in result["reason"]


def test_source_not_in_transcript_is_fabricated(make_mapping_entry):
    entry = make_mapping_entry(doc_source="framework_docs/topics/db/models.txt")
    result = citation_validator.check(entry, _transcript())
    assert result["passed"] is False
    assert "FABRICATED CITATION" in result["reason"]


def test_local_tier_but_fetched_via_web_fetch_is_metric_gaming(make_mapping_entry):
    entry = make_mapping_entry(
        doc_source="framework_docs/topics/db/models.txt",
        doc_source_tier="local",
    )
    record = ToolCallRecord(
        tool_name="web_fetch_scoped",
        source="framework_docs/topics/db/models.txt",
        retrieved_content="A field is used to store data on a model.",
        timestamp="0",
    )
    result = citation_validator.check(entry, _transcript(record))
    assert result["passed"] is False
    assert "METRIC GAMING DETECTED" in result["reason"]


def test_fallback_tier_but_fetched_via_read_file_is_metric_gaming(make_mapping_entry):
    entry = make_mapping_entry(
        doc_source="https://docs.djangoproject.com/topics/db/models/",
        doc_source_tier="fallback",
    )
    record = ToolCallRecord(
        tool_name="read_file",
        source="https://docs.djangoproject.com/topics/db/models/",
        retrieved_content="A field is used to store data on a model.",
        timestamp="0",
    )
    result = citation_validator.check(entry, _transcript(record))
    assert result["passed"] is False
    assert "METRIC GAMING DETECTED" in result["reason"]


def test_snippet_not_substring_of_retrieved_content_fails(make_mapping_entry):
    entry = make_mapping_entry(
        doc_source="framework_docs/topics/db/models.txt",
        doc_source_tier="local",
        doc_snippet_claimed="This snippet was never actually read anywhere",
    )
    record = ToolCallRecord(
        tool_name="read_file",
        source="framework_docs/topics/db/models.txt",
        retrieved_content="Completely different content, unrelated text.",
        timestamp="0",
    )
    result = citation_validator.check(entry, _transcript(record))
    assert result["passed"] is False
    assert "paraphrase drift" in result["reason"]


def test_all_correct_passes(make_mapping_entry):
    entry = make_mapping_entry(
        doc_source="framework_docs/topics/db/models.txt",
        doc_source_tier="local",
        doc_snippet_claimed="A field is used to store data",
    )
    record = ToolCallRecord(
        tool_name="read_file",
        source="framework_docs/topics/db/models.txt",
        retrieved_content="A field is used to store data on a model.",
        timestamp="0",
    )
    result = citation_validator.check(entry, _transcript(record))
    assert result["passed"] is True
    assert "Citation verified" in result["reason"]


def test_empty_claimed_snippet_skips_snippet_check(make_mapping_entry):
    """Boundary case: an empty doc_snippet_claimed must not be treated as
    a paraphrase-drift failure -- the snippet check is skipped entirely as
    long as source/tier match. Easy to regress, so tested explicitly."""
    entry = make_mapping_entry(
        doc_source="framework_docs/topics/db/models.txt",
        doc_source_tier="local",
        doc_snippet_claimed="",
    )
    record = ToolCallRecord(
        tool_name="read_file",
        source="framework_docs/topics/db/models.txt",
        retrieved_content="Totally unrelated content that shares nothing.",
        timestamp="0",
    )
    result = citation_validator.check(entry, _transcript(record))
    assert result["passed"] is True


def test_fallback_tier_via_web_search_scoped_passes(make_mapping_entry):
    """web_search_scoped is also a valid fallback-tier tool, not just
    web_fetch_scoped."""
    entry = make_mapping_entry(
        doc_source="https://docs.djangoproject.com/topics/db/models/",
        doc_source_tier="fallback",
        doc_snippet_claimed="A field is used to store data",
    )
    record = ToolCallRecord(
        tool_name="web_search_scoped",
        source="https://docs.djangoproject.com/topics/db/models/",
        retrieved_content="A field is used to store data on a model.",
        timestamp="0",
    )
    result = citation_validator.check(entry, _transcript(record))
    assert result["passed"] is True
