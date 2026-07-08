"""
config/permissions.py

Declarative filesystem permission rules for create_deep_agent(permissions=...).
Evaluated top-down, first-match-wins. Unmatched operations default to ALLOWED
in the underlying framework -- rule 5 below exists specifically to close that
gap rather than trust the absence of a rule.

Per-project layout (see scripts/fetch_sources.py and projects/*/config.yaml):

  projects/<slug>/config.yaml       -> read-only. Source-of-truth for what
                                        the agent is allowed to fetch/use.
                                        The agent must not be able to widen
                                        its own doc sources or fallback
                                        allowlist.
  projects/<slug>/target_repo/      -> read-only. The evidence.
  projects/<slug>/framework_docs/   -> read-only. Pre-fetched, pinned docs.
                                        Populated by scripts/fetch_sources.py,
                                        never by the agent itself.
  projects/<slug>/workspace/        -> read/write. Case notes, mappings,
                                        flagged items, external-reference log.

gates/ and scripts/ are fully denied -- a validator or fetch script the
agent can edit is not a gate.

NOTE: these rules govern the virtual filesystem tools (ls/read_file/
write_file/edit_file/glob/grep). They do NOT govern network tools
(web_search/web_fetch) -- doc-grounder's fallback domain restriction is
enforced separately, at tool-construction time, gated additionally by
each project's own fallback.enabled flag (see agents/scoped_tools.py).
"""

PERMISSIONS = [
    # 1. Hard-deny writes/edits/execute on gates/ and scripts/ -- the
    #    validation logic and the fetch mechanism must sit outside agent
    #    write access entirely.
    {
        "paths": ["gates/**", "scripts/**"],
        "operations": ["write", "edit", "execute"],
        "mode": "deny",
    },
    # 2. Hard-deny writes/edits/execute on every project's source-of-truth:
    #    its config, its target repo, and its pre-fetched docs.
    {
        "paths": [
            "projects/*/config.yaml",
            "projects/*/target_repo/**",
            "projects/*/framework_docs/**",
        ],
        "operations": ["write", "edit", "execute"],
        "mode": "deny",
    },
    # 3. Those same paths are readable/greppable -- that's the point.
    {
        "paths": [
            "projects/*/config.yaml",
            "projects/*/target_repo/**",
            "projects/*/framework_docs/**",
        ],
        "operations": ["read", "glob", "grep"],
        "mode": "allow",
    },
    # 4. Each project's own workspace is fully read/write.
    {
        "paths": ["projects/*/workspace/**"],
        "operations": ["read", "write", "edit", "glob", "grep"],
        "mode": "allow",
    },
    # 5. Catch-all: deny write/edit/execute everywhere else not already
    #    matched above. Closes the "unmatched = allowed" default rather
    #    than relying on convention.
    {
        "paths": ["**"],
        "operations": ["write", "edit", "execute"],
        "mode": "deny",
    },
    # 6. Reads remain open elsewhere (skills/, AGENTS.md, config templates).
    {
        "paths": ["**"],
        "operations": ["read", "glob", "grep"],
        "mode": "allow",
    },
]
