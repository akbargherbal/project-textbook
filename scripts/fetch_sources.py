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


def _clone(git_url: str, ref: str | None, dest: Path, subpath: str | None):
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


def fetch(project_slug: str):
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
        )
    else:
        print("framework_docs.source is 'local' -- nothing to fetch. "
              "Populate projects/<slug>/framework_docs/ yourself.")

    repo_cfg = cfg.get("target_repo", {})
    if repo_cfg.get("source") == "git":
        print(f"Fetching target_repo @ {repo_cfg.get('ref') or 'default branch'}...")
        _clone(repo_cfg["git_url"], repo_cfg.get("ref"),
               project_dir / "target_repo", None)
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
    args = parser.parse_args()
    fetch(args.project)


if __name__ == "__main__":
    main()
