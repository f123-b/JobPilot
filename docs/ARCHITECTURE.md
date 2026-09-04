# JobPilot V0.3-2 Architecture

## 1. Responsibility split

| Layer | Responsibility |
|---|---|
| Planner Agent | task-aware safe plan generation |
| Resume Agent | conservative profile extraction + resume indexing |
| Search Agent | Browser Use structured job discovery |
| Ranking Agent | Resume RAG retrieval + hybrid ranking + durable memory adjustment |
| Browser Agent | research / approved application execution |
| Evaluation Agent | quality gate and retryability decision |
| Resume Vector Store | pgvector or SQLite vector persistence |
| Long-term Memory | user preferences + job lifecycle states |
| LangGraph Checkpointer | thread-scoped graph state persistence |

## 2. Persistence boundaries

JobPilot intentionally separates three persistence types.

### Operational persistence

SQLite stores tasks, traces, job records, workflow metadata, user memory and job memory.

### Thread persistence

LangGraph checkpointers persist graph snapshots keyed by `workflow_thread_id`.

```text
jobpilot-task-42
      |
      +-- planner checkpoint
      +-- search checkpoint
      +-- ranking checkpoint
      +-- evaluation checkpoint
```

Backend order in `auto` mode:

```text
POSTGRES_URL present -> AsyncPostgresSaver
otherwise            -> AsyncSqliteSaver
package unavailable  -> InMemorySaver
```

### Retrieval persistence

Resume chunks and embeddings are stored separately from graph state:

```text
(user_id, source_id, chunk_index, section, content, embedding, metadata)
```

With PostgreSQL the embedding column is `vector(VECTOR_DIM)` and queries use cosine distance. The local fallback stores vectors as JSON in SQLite and computes cosine similarity in Python.

## 3. Resume indexing

```text
raw bytes
  |
  +-- .txt/.md -> UTF-8
  +-- .pdf     -> pypdf
  +-- .docx    -> python-docx
  |
  v
section-aware line normalization
  |
  v
chunking (max chars + overlap)
  |
  v
embedding
  |
  v
replace chunks for (user_id, source_id)
```

`source_id` includes a content hash so a changed resume becomes a distinct retrieval source.

## 4. Evidence-grounded ranking

For each discovered job:

1. Build JD query text.
2. Retrieve top-k resume chunks for the active user/resume source.
3. Run deterministic skill + semantic match against retrieved evidence.
4. Combine match score with retrieval similarity.
5. Apply persistent preference boosts (currently target location).
6. Apply long-term job-memory rules (currently rejected-job down-rank).
7. Return `RankedJob` including evidence and memory status.

This makes ranking auditable: the UI/API can show which resume lines supported the score.

## 5. Long-term memory

### User memory

Key-value values scoped by `user_id`.

Examples:

- `target_location`
- `target_role`
- `salary_expectation`
- `preferred_industry`

Planner reloads user memory at workflow start. Search objectives inherit it through the plan and Ranking Agent uses relevant preferences directly.

### Job memory

Lifecycle status scoped by `(user_id, job_fingerprint)`:

```text
seen -> saved -> applied -> interview -> offer
            \
             -> rejected
```

Search marks newly discovered jobs as `seen` without overwriting stronger prior states.

## 6. Recovery path

A task is created with a stable thread ID:

```text
workflow_thread_id = jobpilot-task-{task_id}
```

Normal invocation passes it to LangGraph config. `/api/tasks/{id}/resume` schedules the same task with the same thread ID, allowing a persistent checkpointer to reuse the existing thread state rather than creating an unrelated run.

## 7. Safety

- application tasks always require approval;
- planner output is canonicalized by task type;
- missing resume evidence is not fabricated;
- rejected/applied memory changes ranking but never creates application side effects;
- CAPTCHAs and access controls are not bypassed.
