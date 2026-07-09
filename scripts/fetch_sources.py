#!/usr/bin/env python3
"""
scripts/fetch_sources.py

Pre-fetches a project's framework_docs/ (and optionally target_repo/) from
git, per projects/<slug>/config.yaml, BEFORE any agent runs. This is the
"bring the docs local first" step -- it runs once (or whenever you
re-pin a version), outside the agent loop entirely. The agent never
initiates a clone itself; it only ever reads what's already on disk.

Usage:
    python scripts/fetch_sources.py --project django-example

Deliberately NOT wired into main.py's run path -- fetching is a distinct,
infrequent, human-triggered operation. Re-running an agent shouldn't
silently re-clone or mutate framework_docs/ underneath a session that
might be mid-investigation.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

PROJECTS_DIR = Path(__file__).parent.parent / "projects"


def _check_for_accidental_nesting(dest: Path, subpath: str | None, force: bool) -> None:
    """
    Catch the "cloned repo's real content lives one directory deeper than
    expected" mistake right after copying, instead of letting it surface
    hours later as every downstream reference failing structural_check.py.

    Heuristic: if `dest` ends up containing exactly one entry, and that
    entry is a directory (not e.g. a single README), the clone almost
    certainly landed a repo-name wrapper folder instead of the repo's
    actual contents -- the same shape that produced
    target_repo/arabic_diacritization_deepagent/... instead of
    target_repo/... directly. `subpath` exists precisely to point past
    this, so if it wasn't set, this is very likely a missing `subpath`
    rather than a genuinely single-subfolder repo.
    """
    entries = [p for p in dest.iterdir() if p.name != ".gitkeep"]
    if len(entries) == 1 and entries[0].is_dir():
        message = (
            f"  WARNING: {dest} contains a single subdirectory "
            f"('{entries[0].name}/') and nothing else at its root. This "
            f"usually means the repo's real content lives inside that "
            f"subfolder, not at the repo root -- add "
            f"`subpath: \"{entries[0].name}\"` to this source's config.yaml "
            f"entry to clone the correct level."
        )
        if subpath:
            # They already gave a subpath and still got single-dir nesting
            # -- less likely to be this exact mistake, so just note it.
            print(message + " (subpath was already set -- double-check it's correct.)")
            return
        if force:
            print(message + " Proceeding anyway because --force was passed.")
            return
        print(message, file=sys.stderr)
        print(
            "  Refusing to proceed without --force (this almost always breaks "
            "gates/structural_check.py's path resolution downstream).",
            file=sys.stderr,
        )
        sys.exit(1)


def _clone(git_url: str, ref: str | None, dest: Path, subpath: str | None, force: bool = False):
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [git_url, tmp]
        print(f"  $ {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  FAILED: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        source_path = Path(tmp) / subpath if subpath else Path(tmp)
        if not source_path.exists():
            print(f"  FAILED: subpath '{subpath}' not found in cloned repo",
                  file=sys.stderr)
            sys.exit(1)

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source_path, dest, ignore=shutil.ignore_patterns(".git"))
        print(f"  Copied to {dest}")

        _check_for_accidental_nesting(dest, subpath, force)


def fetch(project_slug: str, force: bool = False):
    project_dir = PROJECTS_DIR / project_slug
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        print(f"No config.yaml at {config_path}. Copy "
              f"config/project.template.yaml there first.", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    docs_cfg = cfg.get("framework_docs", {})
    if docs_cfg.get("source") == "git":
        print(f"Fetching framework_docs for {cfg.get('framework_name')} "
              f"@ {docs_cfg.get('ref') or 'default branch'}...")
        if not docs_cfg.get("ref"):
            print("  WARNING: no ref pinned -- freshness_check.py will not "
                  "be able to confirm this matches target_repo's version. "
                  "Strongly recommend pinning a tag/branch.")
        _clone(
            docs_cfg["git_url"],
            docs_cfg.get("ref"),
            project_dir / "framework_docs",
            docs_cfg.get("subpath"),
            force=force,
        )
    else:
        print("framework_docs.source is 'local' -- nothing to fetch. "
              "Populate projects/<slug>/framework_docs/ yourself.")

    repo_cfg = cfg.get("target_repo", {})
    if repo_cfg.get("source") == "git":
        print(f"Fetching target_repo @ {repo_cfg.get('ref') or 'default branch'}...")
        # NOTE: this used to hardcode subpath=None regardless of what was
        # in config.yaml -- framework_docs supported `subpath` for exactly
        # this "repo's content is nested inside a subfolder" case, but
        # target_repo silently didn't. That mismatch is what caused
        # target_repo/arabic_diacritization_deepagent/... instead of
        # target_repo/... directly. Now reads the same key, the same way.
        _clone(repo_cfg["git_url"], repo_cfg.get("ref"),
               project_dir / "target_repo", repo_cfg.get("subpath"),
               force=force)
    else:
        print("target_repo.source is 'local' -- drop the project you're "
              "studying into "
              f"{project_dir / 'target_repo'} yourself.")

    print("\nDone. framework_docs/ and target_repo/ (where fetched) are "
          "now pinned, local, and read-only to the agent per "
          "config/permissions.py.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True,
                         help="Project slug under projects/ (matches its config.yaml)")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Proceed even if a clone looks like it landed a single "
            "repo-name wrapper folder instead of the repo's real "
            "contents (see _check_for_accidental_nesting)."
        ),
    )
    args = parser.parse_args()
    fetch(args.project, force=args.force)


if __name__ == "__main__":
    main()
