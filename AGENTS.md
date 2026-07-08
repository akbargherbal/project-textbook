# AGENTS.md — persistent memory

Read by the orchestrator at the start of every session, per project.

## House style for mappings

Every entry in `projects/<slug>/workspace/mappings/` follows this shape:

```
## <repo file/symbol>
**Concept:** <framework concept name>
**Why it's here:** <1-3 sentences, grounded in the actual repo code>
**Doc source:** <local file path OR fallback URL>
**Doc source tier:** local | fallback
**Doc snippet:** <what was actually read, closely paraphrased>
**Gate status:** <passed | flagged: reason>
```

- Prefer "why is this here" framing over "what is this" — the question
  should be motivated by seeing the pattern in use first.
- doc-grounder checks `framework_docs/` (local, pre-fetched, pinned)
  BEFORE any fallback web search. If a mapping entry's doc source tier is
  "fallback," that's worth noting as slightly less trustworthy than
  "local" — local docs are pinned to the exact version the repo uses;
  fallback sources are whatever's live on the internet right now.
- If doc-grounder cannot find a grounded source anywhere permitted, the
  mapping entry says so explicitly. Do not let a gap get papered over
  with a plausible-sounding but ungrounded explanation.

## On external references found in framework_docs/

`gates/external_reference_scan.py` runs independently of the agent
session and logs every outbound link found inside the pre-fetched docs to
`workspace/notes/external_references.md`. This is informational, not
something the orchestrator acts on directly. If you (the human) decide a
flagged external reference is worth including as a source, add its domain
to that project's `fallback.allowed_domains` in `config.yaml` — the
agent cannot do this itself (config.yaml is write-denied to it).

## Known repo quirks (fill in per project)

- (empty — populate as investigation proceeds)

## Known false positives from gates (fill in per project)

- (empty)
