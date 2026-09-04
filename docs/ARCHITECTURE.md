# JobPilot Architecture

## Agent layer

| Layer | Responsibility |
|---|---|
| Planner Agent | task-aware safe plan generation |
| Resume Agent | conservative profile extraction + resume indexing |
| Search Agent | Browser Use structured job discovery |
| Ranking Agent | Resume RAG retrieval + hybrid ranking + memory adjustment |
| Browser Agent | research / approved application execution |
| Evaluation Agent | quality gate and retryability decision |

## Persistence boundaries

JobPilot separates operational data, workflow checkpoints and retrieval vectors.

### Operational persistence

V0.4 supports SQLite locally and PostgreSQL in the production-style stack. The `app/storage/` package persists jobs, tasks, traces, user/job memory, queue state, usage events and benchmark runs. `app/db.py` remains a compatibility facade.

### Thread persistence

LangGraph checkpointers persist graph snapshots keyed by stable `workflow_thread_id`.

```text
jobpilot-task-42
      |
      +-- planner checkpoint
      +-- search checkpoint
      +-- ranking checkpoint
      +-- evaluation checkpoint
```

### Retrieval persistence

Resume chunks and embeddings are stored separately from graph state. PostgreSQL uses pgvector; the local fallback stores vectors in SQLite and computes cosine similarity in Python.

## Evidence-grounded ranking

For each discovered job:

1. Build JD query text.
2. Retrieve top-k resume chunks.
3. Run deterministic skill + semantic matching against evidence.
4. Combine match score with retrieval similarity.
5. Apply persistent preferences and job-memory rules.
6. Return auditable evidence with the ranking.

## V0.4 production runtime

```text
FastAPI -> task_queue -> Worker -> Multi-Agent LangGraph -> Evaluation -> terminal state
```

The queue is persisted with lease ownership. SQLite uses an atomic single-host claim; PostgreSQL uses `FOR UPDATE SKIP LOCKED` for multiple workers.

Operational state includes `usage_events`, `failure_category` and `benchmark_runs`. Agent-level retry remains in LangGraph; worker retry handles runtime/infrastructure failures.

## Safety

- application tasks always require approval;
- planner output is canonicalized by task type;
- missing resume evidence is not fabricated;
- CAPTCHAs and access controls are not bypassed;
- irreversible actions remain behind Human-in-the-loop.
