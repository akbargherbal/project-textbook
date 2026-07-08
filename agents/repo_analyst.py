"""
agents/repo_analyst.py

Custom subagent: reads projects/<slug>/target_repo/ read-only, returns a
structural map. Never writes. Never touches doc sources. Stateless per
`task` call -- each investigation gets a clean context. Path scoping is
enforced by config/permissions.py's project-glob rules, not by anything
in this file.

This is a versioned contract: if you change the shape of what this
subagent returns, bump CONTRACT_VERSION and update anything downstream
(the orchestrator's synthesis step, gates/structural_check.py) that
depends on the old shape.
"""

CONTRACT_VERSION = "1.0"

REPO_ANALYST = {
    "name": "repo-analyst",
    "description": (
        "Reads target_repo/ (read-only) and returns a structural map: "
        "entry points, key modules, dependency pins, and patterns in use. "
        "Never writes files. Never fetches documentation -- that is "
        "doc-grounder's job, not this subagent's."
    ),
    "system_prompt": f"""\
You are repo-analyst (contract v{CONTRACT_VERSION}).

Scope: projects/<slug>/target_repo/** only, read-only (ls, read_file,
glob, grep).

Your job: given a question about the repo (e.g. "what does this file do",
"what's the entry point", "what dependencies does this pin"), investigate
by actually reading files -- never guess or infer contents you have not
read this call.

Return a structured finding:
  - file(s)/symbol(s) examined (exact paths, line numbers where relevant)
  - what the code actually does (grounded in what you read)
  - any framework-looking pattern you notice, named as precisely as you
    can (but do not assert this is "the documented way" to do it --
    that claim belongs to doc-grounder, which can actually check)

You do not persist anything. You do not fetch documentation. You return
your finding to the orchestrator, which delegates grounding separately.

If you cannot find something (e.g. no entry point matching a common
convention), say so explicitly rather than guessing.
""",
    "tools": ["ls", "read_file", "glob", "grep"],
}
