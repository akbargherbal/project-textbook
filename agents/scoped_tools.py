"""
agents/scoped_tools.py

Builds custom, project-scoped web search and fetch tools. Gated by the
project's fallback rules (allowed_domains, fallback enabled, etc.)
"""

import re
from urllib.parse import urlparse

from langchain_core.tools import tool

# Simple fallback search simulation -- in a real deployment this would
# call Tavily/DuckDuckGo, but restricted to the allowed domains.
_SIMULATED_RESULTS = {
    "docs.langchain.com": (
        "LangChain Documentation:\n"
        "- Use create_react_agent(model, tools) to run an agent with tools.\n"
        "- Use FilesystemPermission(paths, operations, mode) for sandbox rules."
    ),
}


def build_scoped_web_tools(project_config: dict):
    """
    Build custom versions of search and fetch tools that are constrained by
    the project's fallback rules (allowed_domains, fallback enabled, etc.)
    """
    allowed_domains = project_config.get("fallback", {}).get("allowed_domains", [])

    @tool
    def web_search(query: str) -> str:
        """
        Search the web for up-to-date documentation on external APIs and libraries.
        This search is restricted to the fallback allowlist.
        """
        results = []
        for domain in allowed_domains:
            if domain in _SIMULATED_RESULTS:
                results.append(f"[{domain}] {_SIMULATED_RESULTS[domain]}")
        if not results:
            return f"No results found on fallback allowed domains {allowed_domains}."
        return "\n\n".join(results)

    @tool
    def web_fetch(url: str) -> str:
        """
        Fetch the exact raw content of an external web page.
        Only URLs belonging to the fallback allowed domains are fetched.
        """
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]

        if not any(host == d or host.endswith("." + d) for d in allowed_domains):
            return (
                f"Error: Domain '{host}' is not on the fallback allowed_domains list."
            )

        if host in _SIMULATED_RESULTS:
            return f"--- Content of {url} ---\n{_SIMULATED_RESULTS[host]}"
        return f"Error: Fetch simulated failed for {url} (no content mocked)."

    return web_search, web_fetch
