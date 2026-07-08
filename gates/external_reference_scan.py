"""
gates/external_reference_scan.py

NOT one of the four orthogonal verification axes (Structural / Grounding /
Security / Freshness) from the original design -- this is a fifth,
different kind of mechanism: a NOTIFIER, not a pass/fail gate. It doesn't
block a mapping entry from being written. It records, for your review,
every place the pre-fetched framework_docs/ points to something outside
itself -- a link to another repo, an external URL, a "see also" reference
to a file that isn't in the local clone.

Why this matters and why it's not the same as the fallback allowlist:
a reference found INSIDE trusted docs is not automatically trustworthy
just because the docs are trusted. Docs can link to third-party blog
posts, deprecated pages, or content that has moved. This mechanism does
not decide whether to fetch that reference -- it surfaces it so a human
decides, and only references landing on the project's OWN fallback
allowlist are even eligible for doc-grounder to fetch automatically, and
only when framework_docs/ didn't answer the question in the first place.

Runs read-only against framework_docs/ (denied write access anyway per
config/permissions.py), writes findings to
projects/<slug>/workspace/notes/external_references.md.
"""
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

# Matches markdown [text](url), bare <url>, and RST `text <url>`_
_LINK_PATTERN = re.compile(
    r"\[[^\]]*\]\((https?://[^\)]+)\)"      # markdown
    r"|<(https?://[^>]+)>"                    # bare angle-bracket
    r"|`[^`]*<(https?://[^>]+)>`_"            # RST
)


def _extract_urls(text: str) -> list[str]:
    urls = []
    for m in _LINK_PATTERN.finditer(text):
        url = m.group(1) or m.group(2) or m.group(3)
        if url:
            urls.append(url)
    return urls


def _host_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_allowlisted(host: str, allowed_domains: list[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def scan_file(doc_file: Path, project_config: dict) -> list[dict]:
    """
    Scan one file under framework_docs/ for outbound references.
    Returns a list of finding dicts; does not write anything itself.
    """
    if project_config.get("external_reference_policy", "flag") != "flag":
        return []

    text = doc_file.read_text(errors="replace")
    allowed_domains = project_config.get("fallback", {}).get("allowed_domains", [])

    findings = []
    for url in _extract_urls(text):
        host = _host_of(url)
        allowlisted = _is_allowlisted(host, allowed_domains)
        findings.append({
            "source_file": str(doc_file),
            "url": url,
            "in_fallback_allowlist": allowlisted,
            "note": (
                "On the fallback allowlist -- doc-grounder MAY fetch this "
                "if the concept isn't otherwise found locally. Still "
                "logged here for visibility."
                if allowlisted else
                "NOT on the fallback allowlist and NOT part of the local "
                "docs. doc-grounder will not fetch this. Review manually: "
                "add to fallback.allowed_domains if you trust it, or "
                "ignore if it's not relevant to learning this framework."
            ),
        })
    return findings


def scan_and_log(project_dir: Path):
    """
    Scans every file in <project_dir>/framework_docs/ and appends findings
    to <project_dir>/workspace/notes/external_references.md.

    Run this once after scripts/fetch_sources.py, or periodically -- it's
    a static scan of the pinned docs, not something that needs to run per
    agent session.
    """
    config_path = project_dir / "config.yaml"
    with open(config_path) as f:
        project_config = yaml.safe_load(f)

    docs_dir = project_dir / "framework_docs"
    log_path = project_dir / "workspace" / "notes" / "external_references.md"

    all_findings = []
    for path in docs_dir.rglob("*"):
        if path.is_file() and path.suffix in (".md", ".rst", ".txt"):
            all_findings.extend(scan_file(path, project_config))

    with open(log_path, "w") as f:
        f.write("# External references found in framework_docs/\n\n")
        f.write(f"Scanned {docs_dir}. {len(all_findings)} outbound "
                f"reference(s) found. None were auto-fetched.\n\n")
        for finding in all_findings:
            f.write(f"## {finding['source_file']}\n")
            f.write(f"- URL: {finding['url']}\n")
            f.write(f"- On fallback allowlist: {finding['in_fallback_allowlist']}\n")
            f.write(f"- {finding['note']}\n\n")

    print(f"Wrote {len(all_findings)} finding(s) to {log_path}")
    return all_findings
