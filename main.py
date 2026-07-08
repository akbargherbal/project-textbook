"""
main.py

Entry point. Loads a project's config.yaml, wires model provider,
permissions, subagents (local-first doc-grounder + repo-analyst), and the
orchestrator prompt into a create_deep_agent() instance.

Prerequisite: run scripts/fetch_sources.py --project <slug> first, so
framework_docs/ (and target_repo/, if git-sourced) exist on disk before
any agent session starts. This script does NOT fetch anything itself --
fetching is a separate, human-triggered, infrequent step.

Usage:
    export MODEL_PROVIDER=deepseek
    export DEEPSEEK_API_KEY=...
    python scripts/fetch_sources.py --project django-example
    python main.py --project django-example

NOTE: the exact create_deep_agent(...) signature should be re-verified
against docs.langchain.com/oss/python/deepagents before running this.
"""
import argparse
import sys
from pathlib import Path

import yaml
from deepagents import create_deep_agent

from backends.model_provider import get_model
from config.permissions import PERMISSIONS
from agents.repo_analyst import REPO_ANALYST
from agents.doc_grounder import DOC_GROUNDER
from agents.orchestrator import build_orchestrator_prompt
from agents.scoped_tools import build_scoped_web_tools
from gates.external_reference_scan import scan_and_log

PROJECTS_DIR = Path(__file__).parent / "projects"


def load_project(project_slug: str) -> dict:
    config_path = PROJECTS_DIR / project_slug / "config.yaml"
    if not config_path.exists():
        print(f"No config.yaml at {config_path}. Copy "
              f"config/project.template.yaml there first.", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def run(project_slug: str, task_description: str):
    project_dir = PROJECTS_DIR / project_slug
    project_config = load_project(project_slug)
    framework_name = project_config.get("framework_name", project_slug)

    for required_dir, label in [
        (project_dir / "target_repo", "target_repo/"),
        (project_dir / "framework_docs", "framework_docs/"),
    ]:
        if not required_dir.exists() or not any(required_dir.iterdir()):
            print(f"{label} is empty for project '{project_slug}'. Run "
                  f"scripts/fetch_sources.py --project {project_slug} first, "
                  f"or populate it manually if source: local.", file=sys.stderr)
            sys.exit(1)

    # Static, one-time-per-fetch scan of framework_docs/ for outbound
    # references. Not part of the agent loop -- run here so it's fresh
    # for this session's review, but it doesn't depend on anything the
    # agent does this run.
    scan_and_log(project_dir)

    model = get_model()

    web_search_scoped, web_fetch_scoped = build_scoped_web_tools(project_config)
    doc_grounder_tools = ["read_file", "glob", "grep"]
    fallback_enabled = project_config.get("fallback", {}).get("enabled", False)
    doc_grounder_with_tools = {
        **DOC_GROUNDER,
        "tools": doc_grounder_tools + ([web_search_scoped, web_fetch_scoped]
                                        if fallback_enabled else []),
    }

    orchestrator_prompt = build_orchestrator_prompt(project_slug, framework_name)

    agent = create_deep_agent(
        model=model,
        tools=[],
        system_prompt=orchestrator_prompt,
        permissions=PERMISSIONS,
        subagents=[REPO_ANALYST, doc_grounder_with_tools],
        # interrupt_on intentionally omitted -- see LIMITATIONS.md
    )

    print(f"Project: {project_slug} ({framework_name})")
    print(f"Fallback web access: {'enabled' if fallback_enabled else 'DISABLED -- local docs only'}")
    print(f"Task: {task_description}\n")

    result = agent.invoke({
        "messages": [{"role": "user", "content": task_description}],
    })

    print("\n--- Gate results ---")
    print("(Wire this section to parse the agent's proposed mapping entries")
    print(" and call gates/*.py's check() functions against the real")
    print(" tool-call transcript. See gates/citation_validator.py's")
    print(" SessionTranscript for the expected shape.)")

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True,
                         help="Project slug under projects/ (matches its config.yaml)")
    parser.add_argument(
        "--task",
        default=(
            "Investigate target_repo/ and produce a code-to-documentation "
            "mapping for the concepts it uses. Follow AGENTS.md house style."
        ),
    )
    args = parser.parse_args()
    run(args.project, args.task)


if __name__ == "__main__":
    main()
