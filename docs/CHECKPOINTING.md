# Persistent checkpointing

`main.py` runs are now backed by LangGraph's `SqliteSaver`, writing every
checkpoint to a single file-backed database at the project root:

```
checkpoints.db
```

This gives the orchestrator three things it didn't have before:

1. **Full execution history** — every graph step (orchestrator turns,
   `task` calls into repo-analyst/doc-grounder, tool calls) is checkpointed
   as it happens, not just logged after the fact.
2. **Human-in-the-loop approval** — every `write_file` call (i.e. every
   time the orchestrator is about to persist a mapping entry to
   `workspace/mappings/`) now pauses and waits for a human decision:
   `approve`, `edit`, or `reject`. See `agents/orchestrator.py` step 5 for
   what's being approved.
3. **Session resumption** — if a run is interrupted (Ctrl+C, a crash, or a
   paused approval you want to answer later), the same `thread_id` picks
   the run back up from its last checkpoint instead of starting over.

## Where the logic lives

- `runtime/checkpointing.py` — builds the `SqliteSaver` against
  `checkpoints.db`, and resolves which `thread_id` a given CLI invocation
  should use.
- `main.py` — wires the checkpointer and `interrupt_on={"write_file": ...}`
  into `create_deep_agent(...)`, and contains the approval-prompt /
  resume-until-settled loop (`_prompt_for_decisions`, `_run_until_settled`).

## Running a session

```bash
python main.py --project django-example
```

Output includes the thread ID that was generated for this run:

```
Project: django-example (Django)
Fallback web access: enabled
Thread: django-example-3f9a1c2b0d7e (new session)
Task: Investigate target_repo/ and produce a code-to-documentation mapping...
```

That thread ID is also written to
`projects/<slug>/workspace/.last_thread_id` purely as a CLI convenience —
the actual state lives in `checkpoints.db`, keyed by `thread_id`.

## Approving a write

When the orchestrator calls `write_file` to persist a mapping entry, the
run pauses:

```
--- Human approval required (see checkpoints.db for full history) ---

Tool: write_file
Args: {'path': 'projects/django-example/workspace/mappings/models_py.md', 'content': '...'}
Decision [approve/edit/reject]:
```

Type `approve`, `edit`, or `reject` and the run continues. If multiple
`write_file` calls are pending at once, you'll be prompted for each in
order.

## Resuming a paused or interrupted session

If you stopped the process (Ctrl+C, terminal closed, machine restarted,
etc.) while a run was paused on an approval — or mid-run generally — pick
it back up with:

```bash
# Reuses the last thread_id recorded for this project
python main.py --project django-example --resume

# Or target a specific thread explicitly
python main.py --project django-example --resume --thread-id django-example-3f9a1c2b0d7e
```

`--resume` skips issuing a new task. It inspects the thread's saved state:

- If it was paused on an approval, you're prompted for a decision exactly
  as if the process had never stopped.
- If it was killed mid-run with no pending approval, LangGraph continues
  execution from the last completed checkpoint.
- If the thread already ran to completion, `main.py` says so and starts a
  fresh task on that same thread ID instead of doing nothing.

## Querying checkpoints.db directly

`SqliteSaver` creates two tables: `checkpoints` (one row per graph
superstep, per thread) and `writes` (pending/intermediate channel writes
within a step, including interrupt payloads). Both are plain SQLite —
useful for post-mortem analysis without touching Python at all.

```bash
sqlite3 checkpoints.db
```

List every thread that has checkpoint history:

```sql
SELECT DISTINCT thread_id FROM checkpoints;
```

Count checkpoints (i.e. execution steps) per thread, most active first:

```sql
SELECT thread_id, COUNT(*) AS steps
FROM checkpoints
GROUP BY thread_id
ORDER BY steps DESC;
```

Find the most recent checkpoint for a given thread (its current
"resume point"):

```sql
SELECT checkpoint_id, parent_checkpoint_id, metadata
FROM checkpoints
WHERE thread_id = 'django-example-3f9a1c2b0d7e'
ORDER BY checkpoint_id DESC
LIMIT 1;
```

`metadata` is a JSON blob (source, step number, writes summary) — useful
for a quick eyeball without deserializing the full checkpoint blob. The
`checkpoint` column itself is a serialized (msgpack/JSON-plus) blob
containing the actual graph state, including message history and any
subagent-tool-call bookkeeping deepagents attaches to state; it's not
meant to be read as plain SQL text, but its presence per row is exactly
the "complete execution history" this system is meant to capture.

Inspect pending writes (including interrupts awaiting a decision) for a
thread:

```sql
SELECT thread_id, checkpoint_id, task_id, channel, type
FROM writes
WHERE thread_id = 'django-example-3f9a1c2b0d7e'
ORDER BY checkpoint_id DESC;
```

## Notes / things worth re-verifying

Following this scaffold's existing convention (see `LIMITATIONS.md`'s
"re-verify before shipping" section): the exact `interrupt_on` /
`Command(resume=...)` payload shapes, and `SqliteSaver`'s table layout,
come from `docs.langchain.com/oss/python/deepagents/human-in-the-loop` and
`docs.langchain.com/oss/python/langgraph/persistence` as of this change —
re-check both if `deepagents`/`langgraph` are upgraded, since this is a
fast-moving part of the framework.

`SqliteSaver` is explicitly documented as a lightweight, single-process,
synchronous checkpointer — a good fit for this CLI's one-shot-process
usage, but not something to reach for if this scaffold ever grows a
concurrent server in front of it (at which point `PostgresSaver` or
`AsyncSqliteSaver` would be the things to look at instead).
