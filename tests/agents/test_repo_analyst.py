"""
tests/agents/test_repo_analyst.py

Static contract (dict), not runtime behavior.
"""

import pytest

from agents.repo_analyst import REPO_ANALYST, CONTRACT_VERSION

pytestmark = pytest.mark.unit


def test_tools_contains_ls():
    assert "ls" in REPO_ANALYST["tools"]


def test_tools_do_not_contain_write_capable_tools():
    """The 'never writes' invariant from the docstring."""
    write_capable = {"write_file", "edit_file"}
    assert write_capable.isdisjoint(set(REPO_ANALYST["tools"]))


def test_required_keys_present():
    for key in ("name", "description", "system_prompt", "tools"):
        assert key in REPO_ANALYST


def test_name_is_repo_analyst():
    assert REPO_ANALYST["name"] == "repo-analyst"


def test_contract_version_is_a_string():
    assert isinstance(CONTRACT_VERSION, str)


def test_description_mentions_read_only_and_no_doc_fetching():
    description = REPO_ANALYST["description"].lower()
    assert "read-only" in description or "never writes" in description
    assert "documentation" in description
