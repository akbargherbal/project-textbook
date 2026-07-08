"""
tests/agents/test_scoped_tools.py

build_scoped_web_tools returns two LangChain @tool-wrapped callables.
Call them via .invoke({...}) so the test also catches decorator/
signature drift, not just the undecorated function body.
"""

import pytest

from agents.scoped_tools import build_scoped_web_tools

pytestmark = pytest.mark.unit


def _tools(allowed_domains):
    cfg = {"fallback": {"allowed_domains": allowed_domains}}
    return build_scoped_web_tools(cfg)


def test_web_search_with_empty_allowed_domains_returns_no_results():
    web_search, _ = _tools([])
    result = web_search.invoke({"query": "anything"})
    assert "No results found" in result


def test_web_search_with_known_domain_returns_simulated_content():
    web_search, _ = _tools(["docs.langchain.com"])
    result = web_search.invoke({"query": "how do I use tools"})
    assert "docs.langchain.com" in result
    assert "create_react_agent" in result


def test_web_fetch_domain_not_allowed_returns_error_string_not_exception():
    _, web_fetch = _tools(["docs.langchain.com"])
    result = web_fetch.invoke({"url": "https://not-allowed.example.com/page"})
    assert "Error" in result
    assert "not on the fallback allowed_domains list" in result


def test_web_fetch_www_prefix_on_allowed_host_succeeds():
    _, web_fetch = _tools(["docs.langchain.com"])
    result = web_fetch.invoke({"url": "https://www.docs.langchain.com/page"})
    assert "Content of" in result
    assert "create_react_agent" in result


def test_web_fetch_allowed_host_not_in_simulated_results_returns_failure_string():
    _, web_fetch = _tools(["docs.djangoproject.com"])
    result = web_fetch.invoke({"url": "https://docs.djangoproject.com/topics/db/"})
    assert "Fetch simulated failed" in result
    assert "no content mocked" in result


def test_web_fetch_subdomain_of_allowed_domain_passes_domain_check():
    """A subdomain of an allowed domain passes the allowlist check (does
    not get the 'not on the fallback allowed_domains list' error), even
    though it then falls through to the 'no content mocked' simulated-
    failure branch since it's not a literal key in _SIMULATED_RESULTS."""
    _, web_fetch = _tools(["docs.langchain.com"])
    result = web_fetch.invoke({"url": "https://sub.docs.langchain.com/page"})
    assert "not on the fallback allowed_domains list" not in result
    assert "Fetch simulated failed" in result
