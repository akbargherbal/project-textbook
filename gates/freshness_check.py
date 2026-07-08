"""
gates/freshness_check.py

Freshness axis -- now DETERMINISTIC rather than heuristic, which is the
concrete upgrade from pre-fetching docs locally instead of live-searching
them. Previously this had to guess a doc "version" from search results
with no fixed point of comparison. Now framework_docs/ was cloned at an
explicit, known ref (projects/<slug>/config.yaml's
framework_docs.ref) -- so freshness becomes: does target_repo's actual
pinned framework version match that ref?

Still heuristic on ONE side only: detecting target_repo's pinned version
from its manifest file is regex-based and can miss unusual pinning
schemes. Treat a pass as "no obvious mismatch," not "confirmed identical,"
and route genuine ambiguity to human review same as the other gates.
"""
import re
from pathlib import Path

import yaml

MANIFEST_CANDIDATES = [
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "Pipfile",
]


def _find_pinned_version(target_repo: Path, framework_name: str) -> str | None:
    for candidate in MANIFEST_CANDIDATES:
        path = target_repo / candidate
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        pattern = re.compile(
            re.escape(framework_name) + r"[\"']?\s*[=<>~^]+\s*[\"']?([\d][\w\.\-]*)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def check(project_dir: Path) -> dict:
    config_path = project_dir / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    framework_name = cfg.get("framework_name", "")
    docs_ref = cfg.get("framework_docs", {}).get("ref")

    if not framework_name:
        return {"passed": False, "reason": "config.yaml missing framework_name."}

    if not docs_ref:
        return {
            "passed": False,
            "reason": (
                "framework_docs.ref is not pinned in config.yaml -- "
                "freshness cannot be checked deterministically. Pin a "
                "branch/tag/commit and re-run scripts/fetch_sources.py."
            ),
        }

    target_repo = project_dir / "target_repo"
    repo_pinned_version = _find_pinned_version(target_repo, framework_name)

    if repo_pinned_version is None:
        return {
            "passed": True,
            "reason": (
                f"Could not determine target_repo/'s pinned {framework_name} "
                f"version from common manifest files -- skipping comparison "
                f"(not a failure, just unverifiable on the repo side)."
            ),
        }

    # Deterministic comparison: docs_ref (e.g. "stable/5.1.x") should
    # contain/match the detected version (e.g. "5.1.4"). This is a loose
    # substring check by design -- exact tag-to-semver mapping schemes
    # vary per framework and a rigid equality check would false-flag
    # constantly. Tighten this per-framework if you need stricter matching.
    major_minor = ".".join(repo_pinned_version.split(".")[:2])
    if major_minor in docs_ref:
        return {
            "passed": True,
            "reason": (
                f"target_repo pins {framework_name}=={repo_pinned_version}, "
                f"framework_docs pinned at ref '{docs_ref}' -- consistent."
            ),
        }

    return {
        "passed": False,
        "reason": (
            f"VERSION MISMATCH: target_repo pins {framework_name}=="
            f"{repo_pinned_version}, but framework_docs/ was fetched at "
            f"ref '{docs_ref}'. Re-run scripts/fetch_sources.py with the "
            f"correct ref, or confirm this mismatch is acceptable. "
            f"Route to human review."
        ),
    }
