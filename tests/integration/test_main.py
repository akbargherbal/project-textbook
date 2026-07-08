"""
tests/test_main.py

Split cleanly into pure-function tests (no mocking) and one heavy-mocked
integration test for run()'s gate-pipeline post-processing.
"""

import pytest

import main

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------
# parse_markdown_mapping
# --------------------------------------------------------------------


def test_parse_markdown_mapping_full_house_style_block():
    content = (
        "## app.py:1\n"
        "**Concept:** assignment\n"
        "**Why it's here:** because it exists\n"
        "**Doc source:** framework_docs/topics/models.txt\n"
        "**Doc source tier:** local\n"
        "**Doc snippet:** A field is used to store data\n"
        "**Gate status:** pending\n"
    )
    parsed = main.parse_markdown_mapping(content)
    assert parsed["repo_reference"] == "app.py:1"
    assert parsed["concept"] == "assignment"
    assert parsed["doc_source"] == "framework_docs/topics/models.txt"
    assert parsed["doc_source_tier"] == "local"
    assert parsed["doc_snippet_claimed"] == "A field is used to store data"


def test_parse_markdown_mapping_missing_optional_fields_default_to_empty_string():
    content = "## app.py:1\n"
    parsed = main.parse_markdown_mapping(content)
    assert parsed["repo_reference"] == "app.py:1"
    assert parsed["concept"] == ""
    assert parsed["doc_source"] == ""
    assert parsed["doc_source_tier"] == ""
    assert parsed["doc_snippet_claimed"] == ""
    # No KeyError should ever be raised for a missing field.


@pytest.mark.parametrize(
    "field_block",
    [
        "**Concept:** assignment",
        "**Concept**: assignment",
    ],
)
def test_parse_markdown_mapping_concept_colon_placement_variants(field_block):
    content = f"## app.py:1\n{field_block}\n"
    parsed = main.parse_markdown_mapping(content)
    assert parsed["concept"] == "assignment"


@pytest.mark.parametrize(
    "field_block",
    [
        "**Doc source:** x.txt",
        "**Doc source**: x.txt",
    ],
)
def test_parse_markdown_mapping_doc_source_colon_placement_variants(field_block):
    content = f"## app.py:1\n{field_block}\n"
    parsed = main.parse_markdown_mapping(content)
    assert parsed["doc_source"] == "x.txt"


@pytest.mark.parametrize(
    "field_block",
    [
        "**Doc source tier:** local",
        "**Doc source tier**: local",
    ],
)
def test_parse_markdown_mapping_doc_source_tier_colon_placement_variants(field_block):
    content = f"## app.py:1\n{field_block}\n"
    parsed = main.parse_markdown_mapping(content)
    assert parsed["doc_source_tier"] == "local"


@pytest.mark.parametrize(
    "field_block",
    [
        "**Doc snippet:** some snippet text",
        "**Doc snippet**: some snippet text",
    ],
)
def test_parse_markdown_mapping_doc_snippet_colon_placement_variants(field_block):
    content = f"## app.py:1\n{field_block}\n"
    parsed = main.parse_markdown_mapping(content)
    assert parsed["doc_snippet_claimed"] == "some snippet text"


def test_parse_markdown_mapping_doubled_backslashes_in_doc_source_normalized():
    """The normalization step replaces a literal double-backslash
    sequence with a forward slash and strips leading/trailing slashes --
    this only fires on doubled backslashes (as produced by some
    Windows-path serializations), not a single backslash. See the
    single-backslash test below, which documents that narrower case."""
    content = (
        "## app.py:1\n**Doc source:** "
        + "framework_docs\\\\\\\\topics\\\\\\\\models.txt\n"
    )
    parsed = main.parse_markdown_mapping(content)
    assert parsed["doc_source"] == "framework_docs/topics/models.txt"


def test_parse_markdown_mapping_leading_slash_stripped():
    """Only a LEADING slash is stripped (.lstrip("/")) -- a trailing
    slash is left as-is."""
    content = "## app.py:1\n**Doc source:** /framework_docs/topics/models.txt\n"
    parsed = main.parse_markdown_mapping(content)
    assert parsed["doc_source"] == "framework_docs/topics/models.txt"


def test_parse_markdown_mapping_single_backslash_is_not_normalized():
    """Documents current behavior rather than assuming it 'just works':
    a single backslash (not doubled) is left untouched by this
    normalization step."""
    content = "## app.py:1\n**Doc source:** framework_docs\\\\topics\\\\models.txt\n"
    parsed = main.parse_markdown_mapping(content)
    assert parsed["doc_source"] == "framework_docs\\\\topics\\\\models.txt"


def test_parse_markdown_mapping_no_header_repo_reference_empty():
    content = "**Concept:** assignment\n**Doc source:** x.txt\n"
    parsed = main.parse_markdown_mapping(content)
    assert parsed["repo_reference"] == ""


# --------------------------------------------------------------------
# parse_mappings_from_text
# --------------------------------------------------------------------


def test_parse_mappings_from_text_two_sections_returns_two_entries():
    text = (
        "## a.py:1\n"
        "**Concept:** first\n"
        "**Doc source:** x.txt\n"
        "\n"
        "## b.py:2\n"
        "**Concept:** second\n"
        "**Doc source:** y.txt\n"
    )
    entries = main.parse_mappings_from_text(text)
    assert len(entries) == 2
    assert entries[0]["parsed"]["repo_reference"] == "a.py:1"
    assert entries[1]["parsed"]["repo_reference"] == "b.py:2"


def test_parse_mappings_from_text_stray_heading_without_field_markers_is_skipped():
    text = (
        "## random heading\n"
        "just some prose, no field markers here.\n"
        "\n"
        "## a.py:1\n"
        "**Concept:** first\n"
        "**Doc source:** x.txt\n"
    )
    entries = main.parse_mappings_from_text(text)
    assert len(entries) == 1
    assert entries[0]["parsed"]["repo_reference"] == "a.py:1"


def test_parse_mappings_from_text_entry_with_no_field_markers_at_all_is_excluded():
    """An entry with a repo_reference but no 'Concept:'/'Doc source:'
    substring at all is correctly excluded per the module's own filter
    condition. This is an explicit 'confirms current behavior' test --
    it looks like it could drop valid-looking entries, so a future
    change to that filter should be a deliberate decision, not an
    accidental regression."""
    text = "## a.py:1\njust prose, no field markers\n"
    entries = main.parse_mappings_from_text(text)
    assert entries == []


def test_parse_mappings_from_text_empty_string_returns_no_entries():
    assert main.parse_mappings_from_text("") == []


# --------------------------------------------------------------------
# _prompt_for_decisions
# --------------------------------------------------------------------


def test_prompt_for_decisions_reprompts_until_valid_choice(monkeypatch):
    responses = iter(["bogus", "approve"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(responses))

    action_requests = [{"name": "write_file", "args": {"path": "x"}}]
    decisions = main._prompt_for_decisions(action_requests, review_configs=[])

    assert decisions == [{"type": "approve"}]


def test_prompt_for_decisions_default_allowed_decisions_when_tool_not_in_review_configs(
    monkeypatch,
):
    """Default allowed_decisions of ["approve", "reject"] is used when a
    tool name isn't present in review_configs."""
    responses = iter(["reject"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(responses))

    action_requests = [{"name": "some_unconfigured_tool", "args": {}}]
    decisions = main._prompt_for_decisions(action_requests, review_configs=[])

    assert decisions == [{"type": "reject"}]


def test_prompt_for_decisions_uses_tool_specific_allowed_decisions(monkeypatch):
    responses = iter(["edit"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(responses))

    action_requests = [{"name": "write_file", "args": {}}]
    review_configs = [
        {
            "action_name": "write_file",
            "allowed_decisions": ["approve", "edit", "reject"],
        }
    ]
    decisions = main._prompt_for_decisions(action_requests, review_configs)

    assert decisions == [{"type": "edit"}]


def test_prompt_for_decisions_multiple_action_requests_in_order(monkeypatch):
    responses = iter(["approve", "reject"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(responses))

    action_requests = [
        {"name": "write_file", "args": {"path": "a"}},
        {"name": "write_file", "args": {"path": "b"}},
    ]
    decisions = main._prompt_for_decisions(action_requests, review_configs=[])

    assert decisions == [{"type": "approve"}, {"type": "reject"}]
