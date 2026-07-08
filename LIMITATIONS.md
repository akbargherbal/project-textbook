# Limitations & Watch-List

## What this scaffold mitigates

- Repo mutation — blocked structurally via `config/permissions.py`.
- Doc-fetch cost and latency for frameworks whose docs are already on
  GitHub — pre-fetched once via `scripts/fetch_sources.py` into a local,
  pinned, read-only `framework_docs/`, instead of live search/scrape on
  every lookup.
- Citation fabrication — `gates/citation_validator.py` diffs claimed
  citations (local or fallback) against the actual tool-call transcript.
- Doc-grounder wandering off-source in fallback mode — enforced at tool
  construction, gated additionally by each project's `fallback.enabled`.
- Version drift between the repo and the docs describing it —
  `gates/freshness_check.py` is now a deterministic comparison of
  `target_repo`'s detected framework version against `framework_docs`'s
  pinned git ref, rather than a heuristic guess with no fixed reference
  point. This was the concrete upgrade from moving to local pre-fetch.
- Silent following of links docs point to outside themselves —
  `gates/external_reference_scan.py` logs every such link for human
  review; nothing gets auto-fetched based on appearing inside trusted
  docs alone.

## What this does NOT mitigate

- `repo-analyst` or `doc-grounder` misreading content they read
  correctly at the byte level. The gates confirm a reference/citation is
  *real*, not that its *interpretation* is right.
- A pre-fetched doc page that is itself wrong, unclear, or answers a
  subtly different question than the one asked. Local-first grounding
  fixes provenance, not correctness of the source.
- Two doc sources (local vs. fallback, or two files within
  `framework_docs/`) disagreeing with each other — the skill files
  instruct doc-grounder to surface this, but nothing gates it.
- Docs repos that don't cleanly separate hand-written markdown from
  generated content (API references built from docstrings, versioned
  redirects). `scripts/fetch_sources.py` clones what's in the repo at the
  pinned ref — if the rendered doc site includes more than what's in git,
  the local clone will be incomplete and you won't necessarily know it.
  Worth a one-time check per framework before relying on this.
- Staleness between fetches: if you never re-run `fetch_sources.py`
  after `target_repo/` moves to a newer framework version,
  `freshness_check.py` will correctly flag the mismatch — but only if
  you run it. Nothing prompts you to re-fetch automatically.

## Re-verify before shipping

- `create_deep_agent(...)`'s exact signature, and whether `permissions=`
  glob rules behave exactly as assumed here (`projects/*/target_repo/**`
  style wildcards).
- Whether built-in web tools accept per-instance `allowed_domains`
  natively vs. needing the wrapper approach in `scoped_tools.py`.
- DeepSeek's current path through `init_chat_model`.

All three are the kind of surface detail that shifts fast on this
framework — check `docs.langchain.com/oss/python/deepagents` first.

## Chattiest / most brittle seam as this grows

Still orchestrator ↔ doc-grounder, specifically the "local vs. fallback"
distinction leaking into downstream consumers of a mapping entry. If you
build anything that reads `workspace/mappings/*.md` programmatically
later, it needs to respect `doc_source_tier` — treating a fallback
citation with the same confidence as a pinned local one erases the exact
distinction this design exists to preserve.

## Highest metric-gaming risk

Same as before: citation fabrication, now with a second variant worth
watching — the agent claiming a "local" tier citation for something it
actually found via fallback (or vice versa), which would misrepresent how
trustworthy/pinned a given mapping entry actually is. The citation
validator checks that *something* was retrieved; it doesn't currently
cross-check the claimed tier against which tool actually fired. Worth
tightening if you see this happen.

## One-line reminder

This plan will not survive contact with a real, messy docs repo
unchanged — the permission rules and the citation gate are the hard
constraints worth keeping as-is; the fetch/subpath mechanics per
framework, and how much fallback each project needs, are the parts built
to flex.
