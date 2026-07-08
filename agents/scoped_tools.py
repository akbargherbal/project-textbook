"""
agents/scoped_tools.py

Builds the FALLBACK web_search / web_fetch tool instances, restricted to
a project's fallback.allowed_domains -- used only when framework_docs/
doesn't answer a question and the project's config permits fallback at
all. If fallback.enabled is False, this returns tools that refuse every
call outright, so doc-grounder has no working path to the open internet
for that project.

NOTE: confirm against current docs.langchain.com/oss/python/deepagents
whether built-in web tools accept constructor-level allowed_domains
natively, or whether the wrapper approach here (filter before the call,
refuse if not allowlisted) is still the right shape.
"""
from urllib.parse import urlparse


def _is_allowed(url: str, allowed_domains: list[str]) -> bool:
    host = urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def build_scoped_web_tools(project_config: dict):
    """
    project_config: the parsed projects/<slug>/config.yaml contents.
    Returns (web_search_scoped, web_fetch_scoped) callables. If
    fallback.enabled is False, both callables refuse unconditionally --
    this is the "fully local, no network" mode for a project.
    """
    fallback_cfg = project_config.get("fallback", {})
    enabled = fallback_cfg.get("enabled", False)
    allowed_domains = fallback_cfg.get("allowed_domains", [])

    def web_search_scoped(query: str) -> str:
        """Search the web, restricted to this project's fallback allowlist."""
        if not enabled:
            return ("REFUSED: fallback.enabled is false for this project. "
                     "framework_docs/ is the only permitted source.")
        # Wire to your chosen search provider. Results MUST be filtered
        # to allowed_domains before being returned to the model.
        raise NotImplementedError(
            f"Wire web_search_scoped to a search provider. Filter results "
            f"to: {allowed_domains}"
        )

    def web_fetch_scoped(url: str) -> str:
        """Fetch a URL, only if fallback is enabled and the URL is allowlisted."""
        if not enabled:
            return ("REFUSED: fallback.enabled is false for this project. "
                     "framework_docs/ is the only permitted source.")
        if not _is_allowed(url, allowed_domains):
            return (
                f"REFUSED: {url} is not in this project's "
                f"fallback.allowed_domains ({allowed_domains})."
            )
        # Wire to your chosen fetch provider.
        raise NotImplementedError("Wire web_fetch_scoped to a fetch provider.")

    return web_search_scoped, web_fetch_scoped
