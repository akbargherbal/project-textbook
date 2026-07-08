# Project-as-Textbook Learning — DeepAgents Scaffold

An agent system that reverse-engineers an existing (often LLM-generated) codebase and maps its implementation to the framework's OWN documentation — pre-fetched and pinned locally, not live-searched — so you learn the framework through your own project instead of reading docs cover to cover.

## Why local-first docs

If the framework's docs are already on GitHub (as Django's are, inside its main repo), there's no reason to pay for live web search/scrape on every lookup. `scripts/fetch_sources.py` clones the docs once, pinned to a specific ref, into `projects/<slug>/framework_docs/`. Agents then read that local, read-only, byte-stable copy via plain filesystem tools — same mechanism as reading the target repo. Live web search becomes a narrow, optional fallback for concepts genuinely not covered locally, and can be disabled entirely per project (`fallback.enabled: false`).

## Two subagents, kept separate on purpose

- **repo-analyst** — read-only on `projects/<slug>/target_repo/`. Never touches docs.
- **doc-grounder** — reads `projects/<slug>/framework_docs/` first. Falls back to a domain-restricted web search only if permitted and needed. Every citation must be something actually read/fetched this session — checked by `gates/citation_validator.py` against the real tool-call transcript, not by asking the model to self-report.

A third mechanism, `gates/external_reference_scan.py`, is NOT a subagent and NOT one of the four verification axes — it's a static scanner that reads `framework_docs/` for outbound links pointing outside itself, and logs them to `workspace/notes/external_references.md` for YOU to review. Nothing gets auto-fetched just because a trusted doc happened to link to it — that's a different trust tier than your explicit fallback allowlist.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Set up a project (one target_repo + one framework_docs source)
cp config/project.template.yaml projects/my-project/config.yaml
# edit projects/my-project/config.yaml

# 2. Pre-fetch the framework's docs locally (once, or whenever you
#    re-pin a version) -- this is a separate, human-triggered step,
#    never something the agent does mid-session
python scripts/fetch_sources.py --project my-project

# 3. If target_repo.source is "local", drop the project you're studying
#    into projects/my-project/target_repo/ yourself

# 4. Pick a model provider
export MODEL_PROVIDER=deepseek
export DEEPSEEK_API_KEY=...

# 5. Run
python main.py --project my-project
```

A concrete example is already scaffolded at `projects/django-example/` — its `config.yaml` points `framework_docs` at `django/django.git`'s `docs/` subpath, pinned to `stable/5.1.x`. Fetch it, drop a Django project you want to learn into its `target_repo/`, and run.

## Checkpointing & approvals

Every run is checkpointed to a file-backed `checkpoints.db` at the project root (see `runtime/checkpointing.py`). Each mapping-entry write now pauses for a human `approve`/`edit`/`reject` decision before it's persisted, and an interrupted or crashed session can be picked back up with:

```bash
python main.py --project my-project --resume
```

Full details, including SQL queries for inspecting `checkpoints.db` directly, are in `docs/CHECKPOINTING.md`.

## Output

- `projects/<slug>/workspace/mappings/` — code-to-doc mappings that passed all three gates.
- `projects/<slug>/workspace/notes/flagged.md` — mappings that failed a gate. Needs your eyes, not another LLM call.
- `projects/<slug>/workspace/notes/external_references.md` — every outbound link found inside the pre-fetched docs, whether or not it's on your fallback allowlist. Review periodically.

## Adding a new framework/repo to learn

1. `cp config/project.template.yaml projects/<new-slug>/config.yaml`, fill in `framework_name`, `framework_docs.git_url` + `ref` (+ `subpath` if docs live inside a larger repo), and `fallback.allowed_domains` if you want a fallback at all.
2. `python scripts/fetch_sources.py --project <new-slug>`
3. Drop the repo you want to learn into `projects/<new-slug>/target_repo/` (or set `target_repo.source: git`).
4. `python main.py --project <new-slug>`

Each project is fully isolated — no shared global doc allowlist or target repo to reconfigure between frameworks, which was the main pain point in the first version of this scaffold.

## What this does NOT guarantee

See `LIMITATIONS.md`.
