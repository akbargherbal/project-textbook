"""
tests/agents/test_doc_grounder.py

Static contract (dict), not runtime behavior -- test the contract, not
an LLM's output.
"""

import pytest

from agents.doc_grounder import DOC_GROUNDER, CONTRACT_VERSION

pytestmark = pytest.mark.unit


def test_tools_are_read_only_local_filesystem_only():
    """Scoped web tools are appended by main.py at runtime, only if
    fallback.enabled -- assert they are ABSENT at this layer."""
    assert DOC_GROUNDER["tools"] == ["read_file", "glob", "grep"]


def test_contract_version_exists_and_is_a_string():
    assert isinstance(DOC_GROUNDER["contract_version"], str)
    assert DOC_GROUNDER["contract_version"] == CONTRACT_VERSION


def test_required_keys_present():
    for key in ("name", "description", "system_prompt", "tools", "contract_version"):
        assert key in DOC_GROUNDER


def test_name_is_doc_grounder():
    assert DOC_GROUNDER["name"] == "doc-grounder"


def test_system_prompt_mentions_local_first_and_no_fabrication():
    prompt = DOC_GROUNDER["system_prompt"]
    assert "framework_docs/" in prompt
    assert "fallback" in prompt.lower()
    assert "No grounded source found" in prompt
