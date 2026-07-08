# Testing Strategy

Audience: an LLM/AI coding agent implementing the test suite for this repo.
Framework: **pytest** (+ `pytest-mock`, `pytest-cov`). No other test runner.

Read this whole document before writing a single test file — the ordering
in "Build order" matters, because later tiers rely on fixtures defined in
earlier ones.

## 0. Ground rules

- **Never hit the network.** `scripts/fetch_sources.py` calls real `git
  clone` and several modules eventually call real model providers
  (OpenAI/Anthropic/DeepSeek/NVIDIA). All of that is mocked. If a test
  would need network access or a real API key to pass, it's written
  wrong — fix the test, don't skip it.
- **Never let a test touch the real repo tree.** Anything that reads or
  writes `projects/<slug>/...`, `checkpoints.db`, or `config.yaml` must
  operate inside `tmp_path`. Build a fake project directory per test, not
  a shared fixture pointing at real `projects/deep-agents/` or
  `projects/django-example/`.
- **Gates are pure functions — test them exhaustively.** `gates/*.py`
  take plain dicts/paths and return `{"passed": bool, "reason": str}`.
  They have zero LangChain/deepagents dependency. This is the
  highest-value, lowest-effort part of the suite — prioritize it.
- **Everything that imports `deepagents`, `langgraph`, or a
  `langchain_*` package must be mocked at the import boundary**, not
  partially exercised. These packages are explicitly called out in
  `LIMITATIONS.md` as fast-moving and only loosely verified against docs
  — the tests must not depend on their real behavior or even on them
  being installed with a working API key.
- **One test file per source file**, mirroring the source tree:

```
tests/
  conftest.py                       # shared fixtures (see §2)
  gates/
    test_structural_check.py
    test_citation_validator.py
    test_freshness_check.py
    test_external_reference_scan.py
  agents/
    test_doc_grounder.py
    test_repo_analyst.py
    test_scoped_tools.py
    test_tool_call_logger.py
    test_orchestrator.py
  backends/
    test_model_provider.py
  config/
    test_permissions.py
  runtime/
    test_checkpointing.py
  scripts/
    test_fetch_sources.py
  test_main.py                      # main.py's own helpers + integration
  integration/
    test_end_to_end_gate_pipeline.py
```

## 1. Build order (do not reorder)

1. `gates/` — pure functions, no mocking required beyond `tmp_path`.
2. `config/permissions.py` — pure data (a list of `FilesystemPermission`),
   test the *rules*, not the enforcement engine itself.
3. `agents/scoped_tools.py`, `agents/tool_call_logger.py` — pure-ish,
   isolated logic (URL/domain matching, callback bookkeeping).
4. `agents/doc_grounder.py`, `agents/repo_analyst.py`,
   `agents/orchestrator.py` — these are mostly static dict/string
   contracts; assert shape and prompt content, not behavior.
5. `backends/model_provider.py` — env-var-driven branching, mock the SDK
   classes.
6. `runtime/checkpointing.py` — real SQLite against `tmp_path`, no mocking
   needed (it's already a lightweight local file).
7. `scripts/fetch_sources.py` — mock `subprocess.run` and `shutil`.
8. `main.py` — parsing/mapping helpers first (pure functions, no mocking),
   then `run()` as an integration test with `create_deep_agent` mocked.
9. `integration/` — wires real gates + real parsing against a fake
   `agent.invoke()` result and a fake tool-call transcript, no mocking of
   gates themselves.

## 2. Shared fixtures (`tests/conftest.py`)

Build these once, reuse everywhere. Sketch:

```python
import shutil
from pathlib import Path
import pytest
import yaml

@pytest.fixture
def project_dir(tmp_path) -> Path:
    """A fake projects/<slug>/ tree with the real subdirectory shape."""
    root = tmp_path / "demo-project"
    for sub in ("target_repo", "framework_docs", "workspace/mappings",
                "workspace/notes"):
        (root / sub).mkdir(parents=True)
    return root

@pytest.fixture
def project_config(project_dir) -> dict:
    cfg = {
        "project_name": "demo-project",
        "framework_name": "Django",
        "target_repo": {"source": "local"},
        "framework_docs": {
            "source": "git",
            "git_url": "https://example.invalid/django/django.git",
            "ref": "stable/5.1.x",
            "subpath": "docs",
        },
        "fallback": {"enabled": True, "allowed_domains": ["docs.djangoproject.com"]},
        "external_reference_policy": "flag",
    }
    (project_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    return cfg

@pytest.fixture
def make_mapping_entry():
    """Factory for a well-formed mapping-entry dict (AGENTS.md house style)."""
    def _make(**overrides):
        entry = {
            "repo_reference": "app/models.py:10",
            "concept": "Django Model field",
            "doc_source": "framework_docs/topics/db/models.txt",
            "doc_source_tier": "local",
            "doc_snippet_claimed": "A field is used to store data",
        }
        entry.update(overrides)
        return entry
    return _make
```

Do **not** put LangChain/deepagents mocks in `conftest.py` globally — scope
those to `tests/test_main.py` and `tests/agents/` fixtures, since most of
the suite (tiers 1–3, 6–7) never imports those packages at all and
shouldn't pay the import cost or risk a version-mismatch collection
error.

## 3. Per-module test plans

### 3.1 `gates/structural_check.py`

Pure, deterministic, file-existence + line-range logic. Cover:

- `repo_reference` missing entirely → fails with a clear reason.
- File path doesn't exist under `target_repo/` → fails.
- Bare file reference (no `:line`) that exists → passes.
- `path:N` where `N` is in range → passes; `N == 0`, `N` beyond EOF → fails.
- `path:N-M` where `M < N` → fails (explicitly tested: "end before start").
- `path:N-M` valid range → passes.
- Windows-style backslashes in `repo_reference` are **not** normalized by
  this module (only `main.py`'s parser does that) — write a test that
  documents this rather than assuming it "just works."

```python
def test_missing_repo_reference_fails(project_dir):
    result = structural_check.check({}, project_dir)
    assert result["passed"] is False

def test_line_out_of_range_fails(project_dir):
    f = project_dir / "target_repo" / "app.py"
    f.write_text("line1\nline2\n")
    result = structural_check.check(
        {"repo_reference": "app.py:99"}, project_dir
    )
    assert result["passed"] is False
    assert "out of range" in result["reason"]
```

### 3.2 `gates/citation_validator.py`

This is the highest-stakes gate (fabrication + metric-gaming detection).
Test every branch of `check()` independently, using
`citation_validator.SessionTranscript` / `ToolCallRecord` directly — do
not go through `agents/tool_call_logger.py` here, that's a separate unit
under test in §3.7.

Required cases:
- No `doc_source` on the entry → fails, reason mentions "ungrounded".
- `doc_source` not present in the transcript at all → fails, reason
  contains "FABRICATED CITATION".
- Tier is `"local"` but the matching transcript record's `tool_name` is
  `web_fetch_scoped` → fails, reason contains "METRIC GAMING DETECTED".
- Tier is `"fallback"` but the matching record's `tool_name` is
  `read_file` → fails, same "METRIC GAMING DETECTED" message.
- Source retrieved correctly, tier matches, but
  `doc_snippet_claimed[:40]` is not a substring of
  `retrieved_content` → fails ("paraphrase drift").
- All of the above correct → passes, reason contains "Citation verified".
- Boundary: `doc_snippet_claimed` is empty string → snippet check is
  skipped entirely (must pass as long as source/tier match) — write this
  as an explicit case since it's easy to regress.

### 3.3 `gates/freshness_check.py`

Mock nothing — write real `pyproject.toml` / `requirements.txt` files
into `tmp_path / "target_repo"`.

- `framework_name` missing from config → fails.
- `framework_docs.ref` missing/falsy → fails, reason mentions "not
  pinned".
- No manifest file matches `MANIFEST_CANDIDATES` → passes with a reason
  noting it's unverifiable (this is a **pass**, not a failure — test this
  explicitly, it's counterintuitive).
- Manifest pins a version whose major.minor is a substring of `ref` (e.g.
  repo pins `5.1.4`, ref is `stable/5.1.x`) → passes.
- Manifest pins a version whose major.minor is **not** in `ref` (e.g.
  repo pins `4.2.1`, ref is `stable/5.1.x`) → fails, reason contains
  "VERSION MISMATCH".
- Parametrize across all four `MANIFEST_CANDIDATES` filenames to confirm
  the regex fires for each (`pyproject.toml`, `requirements.txt`,
  `package.json`, `Pipfile`).

### 3.4 `gates/external_reference_scan.py`

Not a pass/fail gate — a notifier. Test `scan_file()` and `scan_and_log()`
separately.

- `_extract_urls` (via `scan_file`) finds markdown-link, bare
  `<angle-bracket>`, and RST-style URLs — one test per style, plus one
  test with all three mixed in a single fake doc file.
- `external_reference_policy: ignore` in config → `scan_file` returns `[]`
  even if the file contains links.
- A URL whose host is on `fallback.allowed_domains` → finding has
  `in_fallback_allowlist: True` and the "MAY fetch" note.
- A URL whose host is not on the allowlist → `in_fallback_allowlist:
  False` and the "will not fetch... review manually" note.
- `www.` prefix stripping: `www.docs.djangoproject.com` matches an
  allowlist entry of `docs.djangoproject.com`.
- `scan_and_log` writes `workspace/notes/external_references.md` and the
  file contains one `##` section per source file scanned; assert on file
  existence and content, not just the return value.
- `scan_and_log` only walks `.md/.rst/.txt/.mdx` files — drop a `.py` file
  containing a URL into `framework_docs/` and assert it's ignored.

### 3.5 `config/permissions.py`

You are testing a **list of declarative rules**, not an enforcement
engine (that's inside `deepagents`, out of scope). Assert on the shape
and ordering of `PERMISSIONS` directly:

- `PERMISSIONS` is a list, first-match-wins order matters: assert the
  `gates/**` / `scripts/**` write-deny rule appears **before** the
  catch-all `/**` read-allow rule (index comparison), so a future edit
  that reorders the list is caught.
- Each rule's `paths`, `operations`, `mode` are present and `mode` is one
  of `{"allow", "deny"}`.
- There is at least one `write`-`deny` rule covering
  `/projects/*/config.yaml`, `/projects/*/target_repo/**`, and
  `/projects/*/framework_docs/**` together (guards the "agent cannot
  widen its own doc sources" invariant called out in the module
  docstring).
- There is a final catch-all `write`-`deny` on `/**` (rule 5) — this is
  the specific gap-closer the docstring says it exists for; if it's
  missing the test should fail loudly, not silently pass.

If `deepagents.FilesystemPermission` isn't importable in the test
environment, mock it as a simple `namedtuple`/dataclass with `paths`,
`operations`, `mode` fields before importing `config.permissions` — don't
skip this test file on `ImportError`.

### 3.6 `agents/scoped_tools.py`

`build_scoped_web_tools` returns two LangChain `@tool`-wrapped callables.
Call them via `.invoke({...})` or `.func(...)` (check which the installed
`langchain_core` version exposes) rather than calling the undecorated
function directly, so the test also catches decorator/signature drift.

- Empty `allowed_domains` → `web_search` returns "No results found...".
- `allowed_domains=["docs.langchain.com"]` → `web_search` returns content
  containing that domain's simulated result.
- `web_fetch` on a URL whose host is not in `allowed_domains` → returns an
  "Error: Domain ... not on the fallback allowed_domains list" string
  (not an exception).
- `web_fetch` with `www.` prefix on an allowed host → succeeds (mirrors
  the `www.` stripping logic).
- `web_fetch` on an allowed host not present in `_SIMULATED_RESULTS` →
  returns the "Fetch simulated failed" string, not a crash.

### 3.7 `agents/tool_call_logger.py`

This is pure bookkeeping — no LangChain runtime needed, only the
`BaseCallbackHandler` interface shape. Call `on_tool_start` /
`on_tool_end` directly with hand-built args.

- `on_tool_start` with a dict `serialized={"name": "read_file"}` and an
  explicit `inputs=` dict records a call with those inputs.
- `on_tool_start` with only `input_str` (no `inputs=`) and valid JSON
  parses it into a dict.
- `on_tool_start` with `input_str` that is not valid JSON falls back to
  `{"__raw__": input_str}`.
- `on_tool_end` correctly attaches `output` to the matching `run_id`'s
  record; a call to `on_tool_end` with an unknown `run_id` does not raise.
- `build_transcript`:
  - a `read_file` call with `inputs={"file_path":
    "projects/demo/framework_docs/x.txt"}` produces a
    `ToolCallRecord` for **both** the raw path and the
    project-relative path (`framework_docs/x.txt`) — this dual
    registration is load-bearing for `citation_validator.check()` and
    deserves its own test.
  - a `read_file` call with a bare relative path (no `projects/` prefix)
    gets an additional registered source of
    `projects/<slug>/<path>` — assert this transformation explicitly,
    parametrized with `project_slug="demo-project"`.
  - `web_search` / `web_fetch` inputs map to `web_search_scoped` /
    `web_fetch_scoped` tool names in the resulting transcript (naming
    normalization is exactly what downstream `citation_validator`
    depends on).
  - a tool call with no recognizable name (e.g. `"ls"`) is silently
    skipped, not recorded.
  - a call whose resolved `source` is empty string is skipped.

### 3.8 `agents/doc_grounder.py`, `agents/repo_analyst.py`, `agents/orchestrator.py`

These are static contracts (dicts / template strings), not runtime
behavior — test the **contract**, not an LLM's output:

- `DOC_GROUNDER["tools"] == ["read_file", "glob", "grep"]` (scoped web
  tools are appended by `main.py`, not baked in here — assert they are
  **absent** at this layer).
- `DOC_GROUNDER["contract_version"]` exists and is a string.
- `REPO_ANALYST["tools"]` contains `"ls"` and does **not** contain any
  write-capable tool name (`write_file`, `edit_file`) — this is the
  "never writes" invariant from the docstring.
- `build_orchestrator_prompt("demo-project", "Django")` returns a string
  containing both substituted values (`"demo-project"` and `"Django"`
  each appear at least once) and does **not** contain the literal
  placeholder text `"{project_slug}"` or `"{framework_name}"` (catches a
  broken `.format()` silently leaving braces in).
- The orchestrator prompt template contains the exact house-style header
  shape gates depend on — assert the substrings `"## <safe-name>.md"`-style
  guidance and `"**Gate status:**"` appear, since a prompt edit that drops
  this instruction would desync the agent from `main.py`'s parser without
  any other test catching it.

### 3.9 `backends/model_provider.py`

Use `monkeypatch.setenv` / `monkeypatch.delenv` for every env var; mock
`init_chat_model` and `ChatNVIDIA` so no real SDK/network call happens.

```python
def test_unknown_provider_raises(monkeypatch):
    with pytest.raises(ValueError, match="Unknown provider"):
        get_model(provider="not-a-real-provider")

def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="DEEPSEEK_API_KEY"):
        get_model(provider="deepseek")

def test_deepseek_calls_init_chat_model_with_default_timeout(monkeypatch, mocker):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    mock_init = mocker.patch("backends.model_provider.init_chat_model")
    get_model(provider="deepseek")
    args, kwargs = mock_init.call_args
    assert args[0] == "deepseek:deepseek-chat"
    assert kwargs["timeout"] == 300.0

def test_nvidia_provider_sets_client_timeouts(monkeypatch, mocker):
    monkeypatch.setenv("NVIDIA_API_KEY", "fake")
    fake_llm = mocker.MagicMock()
    fake_llm._client = mocker.MagicMock()
    fake_llm._async_client = mocker.MagicMock()
    mock_chat_nvidia = mocker.patch(
        "langchain_nvidia_ai_endpoints.ChatNVIDIA", return_value=fake_llm
    )
    get_model(provider="nvidia")
    assert fake_llm._client.timeout == 300.0
```

Also cover:
- `MODEL_TIMEOUT_SECONDS` env var overrides the default for a non-NVIDIA
  provider (assert `kwargs["timeout"]` reflects it).
- `get_model(provider="nvidia", timeout=45)` sets both
  `llm._client.timeout` and `llm._async_client.timeout` to `45`, **not**
  passed through to `ChatNVIDIA(...)`'s constructor kwargs (this was
  fixed deliberately per the module's own comment — regressing it is a
  real bug class, not cosmetic).
- Provider resolution falls back to `MODEL_PROVIDER` env var, then to
  `"deepseek"` when neither an explicit `provider` arg nor the env var is
  set.

### 3.10 `runtime/checkpointing.py`

Real SQLite is cheap — don't mock it, just point everything at
`tmp_path`.

- `get_checkpointer(tmp_path / "checkpoints.db")` creates the file and
  the `checkpoints` / `writes` tables (query `sqlite_master` to confirm).
- Calling `get_checkpointer` twice against the same path is idempotent
  (no exception on the second `.setup()`).
- `resolve_thread_id` with an explicit `explicit_thread_id` always wins,
  regardless of `resume`, and writes it to
  `workspace/.last_thread_id`.
- `resolve_thread_id(resume=True)` with no marker file present falls back
  to minting a fresh thread id and returns `is_resuming=False`.
- `resolve_thread_id(resume=True)` with an existing marker file returns
  that file's content and `is_resuming=True`.
- `resolve_thread_id(resume=False, explicit_thread_id=None)` always mints
  a new id of the form `f"{project_slug}-{12 hex chars}"` (regex-match
  the shape) and persists it as the new marker.
- Two calls with `resume=False` produce **different** thread ids
  (uuid4-based; a fixed-seed regression would be a real bug).

### 3.11 `scripts/fetch_sources.py`

Mock `subprocess.run` — never invoke real `git`.

- `fetch()` with `framework_docs.source: local` prints/skips without
  calling `subprocess.run` at all.
- `fetch()` with `framework_docs.source: git` and `ref` unset prints a
  warning about freshness before still attempting the clone.
- `_clone` builds the `git clone --depth 1 --branch <ref> <url> <tmp>`
  command correctly when `ref` is set, and omits `--branch ...` when
  `ref` is `None` (assert on the constructed `cmd` list passed to the
  mocked `subprocess.run`, not by parsing stdout).
- `_clone` with a non-zero return code from the mocked `subprocess.run`
  causes `sys.exit(1)` (assert via `pytest.raises(SystemExit)`).
- `_clone` with a `subpath` that doesn't exist in the (mocked/faked)
  cloned tree also exits with code 1, distinctly from the git-failure
  case (use a real temp directory for the "cloned" content here since
  the subpath-existence check touches the real filesystem, only the
  `git clone` subprocess call itself is mocked).
- `_clone` overwrites an existing `dest` directory (pre-create `dest`
  with a stray file inside, assert it's gone after `_clone` runs against
  a faked source tree).
- `fetch()` with a missing `config.yaml` calls `sys.exit(1)` and does not
  raise an unhandled exception.

### 3.12 `main.py`

Split cleanly into **pure-function tests** (no mocking) and **one
integration test** (heavy mocking). Do not try to unit-test
`create_deep_agent(...)`'s internals — that's `deepagents`'s job, not
this repo's.

**Pure functions — test directly, no mocks:**

- `parse_markdown_mapping`: parametrize over the full AGENTS.md house
  style block (all 6 fields present), a block missing optional fields
  (assert empty-string defaults, not `KeyError`), the alternate
  `**Field**:` vs `**Field:**` colon placement for every field that has
  a documented fallback regex, and a `doc_source` containing backslashes
  (assert they're normalized to forward slashes and leading/trailing
  slashes stripped).
- `parse_mappings_from_text`: a string with two `##`-sectioned entries
  returns two parsed dicts; a section containing neither `"Concept:"` nor
  `"Doc source:"` is silently skipped (e.g. a stray `##` heading that
  isn't a mapping entry); an entry with `repo_reference` but no
  `"Concept:"`/`"Doc source:"` substring at all is correctly excluded per
  the module's own filter condition — write this as an explicit
  "confirms current behavior" test even though it looks like it could
  drop valid-looking entries, so a future change to that filter is a
  deliberate decision, not an accidental regression.
- `_prompt_for_decisions`: monkeypatch `builtins.input` to return an
  invalid choice then a valid one, and assert it re-prompts (loops) until
  a value in `allowed_decisions` is entered; assert the default
  `allowed_decisions` of `["approve", "reject"]` is used when a tool name
  isn't present in `review_configs`.

**Gate-pipeline integration (`run()`'s post-processing, §7 in the code):**
this is the highest-value integration test in the repo — it exercises
real `structural_check` + `citation_validator` + `freshness_check`
against on-disk fixtures, with only the agent invocation faked:

```python
def test_passed_and_flagged_entries_are_persisted_correctly(
    project_dir, project_config, mocker
):
    # Arrange: a real target_repo file the structural gate can verify
    (project_dir / "target_repo" / "app.py").write_text("x = 1\n")
    (project_dir / "target_repo" / "requirements.txt").write_text(
        "Django==5.1.4\n"
    )
    (project_dir / "framework_docs" / "topics").mkdir()
    (project_dir / "framework_docs" / "topics" / "models.txt").write_text(
        "A field is used to store data on a model."
    )

    good_entry = (
        "## app.py:1\n"
        "**Concept:** assignment\n"
        "**Doc source:** framework_docs/topics/models.txt\n"
        "**Doc source tier:** local\n"
        "**Doc snippet:** A field is used to store data\n"
    )
    bad_entry = (
        "## does_not_exist.py:1\n"
        "**Concept:** ghost\n"
        "**Doc source:** framework_docs/topics/models.txt\n"
        "**Doc source tier:** local\n"
        "**Doc snippet:** A field is used to store data\n"
    )
    (project_dir / "workspace" / "mappings" / "app_py.md").write_text(good_entry)
    (project_dir / "workspace" / "mappings" / "ghost.md").write_text(bad_entry)

    # Mock everything at the deepagents/model boundary
    mocker.patch("main.PROJECTS_DIR", project_dir.parent)
    mocker.patch("main.get_model", return_value=mocker.MagicMock())
    mocker.patch("main.scan_and_log")
    fake_logger = mocker.MagicMock()
    fake_logger.calls = [
        {
            "name": "read_file",
            "inputs": {"file_path": "projects/demo-project/framework_docs/topics/models.txt"},
            "output": "A field is used to store data on a model.",
        }
    ]
    mocker.patch("main.ToolCallLogger", return_value=fake_logger)
    fake_agent = mocker.MagicMock()
    fake_agent.invoke.return_value = mocker.MagicMock(
        interrupts=[], value={"messages": []}
    )
    mocker.patch("main.create_deep_agent", return_value=fake_agent)

    run("demo-project", "investigate")

    assert (project_dir / "workspace" / "mappings" / "app_py.md").exists()
    assert not (project_dir / "workspace" / "mappings" / "ghost.md").exists()
    flagged = (project_dir / "workspace" / "notes" / "flagged.md").read_text()
    assert "does_not_exist.py" in flagged
```

Additional integration cases worth adding once the above passes:
- Missing `target_repo/` or `framework_docs/` → `run()` calls
  `sys.exit(1)` before ever constructing an agent (assert
  `main.create_deep_agent` was never called, via the mock).
- `_run_until_settled` loops through multiple pending interrupts,
  calling `_prompt_for_decisions` once per `result.interrupts` cycle,
  stopping only once `result.interrupts` is empty (mock `agent.invoke` to
  return an interrupted result once, then a settled one).
- `--resume` path: `pending_state.tasks` has an interrupt → decisions are
  collected and `Command(resume=...)` is used as `initial_input`; no
  interrupt but `pending_state.next` truthy → resumes with `None` input;
  neither → falls through to starting a fresh task on the same thread
  (three separate tests, one per branch in `run()`'s `is_resuming` block).

## 4. Markers and test selection

Add to `pyproject.toml` (or `pytest.ini`):

```ini
[tool.pytest.ini_options]
markers = [
    "unit: fast, no filesystem/subprocess/mocking beyond tmp_path",
    "integration: exercises multiple real modules together, heavier mocking",
]
testpaths = ["tests"]
```

Mark every test in `tests/gates/`, `tests/agents/test_scoped_tools.py`,
`tests/agents/test_tool_call_logger.py`, `tests/config/`,
`tests/runtime/` as `@pytest.mark.unit`. Mark everything in
`tests/integration/` and the gate-pipeline test in `test_main.py` as
`@pytest.mark.integration`. This lets an agent (or CI) run
`pytest -m unit` for a fast inner loop and the full suite before merging.

## 5. Coverage targets

Run with:

```bash
pytest --cov=. --cov-report=term-missing -m "unit or integration"
```

Targets (guidance, not a hard gate to chase blindly):

| Area | Target | Why |
|---|---|---|
| `gates/` | ~100% | Pure functions, deterministic, cheapest to fully cover, and the highest-consequence code in the repo (these are the trust boundary). |
| `agents/tool_call_logger.py` | ~100% | Small, pure, and load-bearing for citation correctness. |
| `agents/scoped_tools.py`, `config/permissions.py` | ~90%+ | Pure logic, easy to fully exercise. |
| `backends/model_provider.py` | ~85%+ | Branchy but fully mockable; don't chase the NVIDIA-specific edge branches at the cost of clarity. |
| `runtime/checkpointing.py` | ~90%+ | Cheap real-SQLite tests, no excuse to skip branches. |
| `scripts/fetch_sources.py` | ~80%+ | Subprocess-mocking has diminishing returns past the core success/failure branches. |
| `main.py` | Pure-function parsers ~95%+; `run()` itself covered by 4-5 integration tests, not line-coverage-chased | `run()`'s orchestration is glue around `deepagents`; over-mocking it line-by-line produces brittle tests that break on every unrelated refactor. |
| `agents/doc_grounder.py`, `agents/repo_analyst.py`, `agents/orchestrator.py` | Contract assertions only, no numeric target | These are prompts/config dicts, not logic — coverage % is meaningless here. |

## 6. What NOT to test

- Do not test that `deepagents.create_deep_agent(...)` builds a working
  agent, that `langgraph`'s `SqliteSaver` persists correctly internally,
  or that `init_chat_model` calls the right HTTP endpoint — these are
  the dependencies' responsibility, and `LIMITATIONS.md` already flags
  their exact signatures as things to re-verify against upstream docs,
  not to pin down here with brittle mocks.
- Do not write a test asserting the literal wording of an LLM-facing
  prompt beyond the specific substrings gates/parsers depend on (§3.8).
  Testing full prompt text turns every prompt-wording improvement into a
  failing test for no safety benefit.
- Do not attempt true end-to-end tests that spin up a real agent loop
  with a real model. If this is ever wanted, it belongs in a manual/CI
  smoke-test script outside `pytest`, gated behind an explicit env var,
  never in the default `pytest` run.

## 7. Definition of done for this suite

- `pytest -m unit` runs in well under 5 seconds with no network access
  and no filesystem writes outside `tmp_path`.
- `pytest` (full suite, unit + integration) passes with no real git
  clone, no real model API call, and no test depending on execution
  order.
- Every gate in `gates/` has a test for each distinct failure `reason`
  string it can produce, not just an aggregate pass/fail check.
- Deleting `checkpoints.db`/`workspace/` fixtures created by a test run
  from `tmp_path` requires no manual cleanup (pytest handles this
  automatically — confirm no test writes outside the `tmp_path`/`mocker`
  sandbox).
