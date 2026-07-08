# SKILL: repo-analysis

Loaded by repo-analyst when investigating target_repo/.

## Order of investigation

1. Look for the entry point first (`main.py`, `app.py`, `manage.py`,
   `index.js`, `Cargo.toml`'s `[[bin]]`, etc. -- depends on the language).
2. Read the dependency manifest before reading application code -- knowing
   which framework version is pinned changes how you interpret patterns
   you see later.
3. Follow imports outward from the entry point rather than reading files
   alphabetically or by directory listing order -- the goal is to
   reconstruct the actual call graph the learner will encounter, not an
   arbitrary traversal.
4. When you notice a pattern that looks like a named framework concept
   (a decorator, a lifecycle hook, a specific base class), record the
   pattern AND exactly where you saw it (file:line) -- doc-grounder needs
   the precise reference to ground it, and structural_check needs it to
   verify the reference is real.

## What NOT to do

- Do not assert what a pattern is "for" based on its name alone (e.g.
  seeing `@app.middleware` and assuming you know what it does from
  general knowledge). Report what you observe the code doing, and let
  doc-grounder supply the authoritative "why."
- Do not read the entire repo indiscriminately if it's large -- prioritize
  files the entry point actually reaches. Note in your finding if you
  stopped short of full coverage and why.

## Placeholder: framework-specific hints

Fill this section in per-target-repo, per the README's re-pointing
instructions. E.g. for a Django project:
- Look for `settings.py`, `urls.py`, `models.py` first.
- Migrations in `*/migrations/` are generated, not hand-written --
  usually not worth deep analysis.
