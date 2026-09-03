# JobPilot V0.2 Architecture

## Goal

JobPilot is an AI job-search and browser-automation agent. V0.2 focuses on agent engineering rather than a single prompt-to-browser call:

- explicit workflow orchestration with LangGraph;
- structured Browser Use output for job discovery;
- deterministic job deduplication and persistence;
- skill + embedding resume/JD matching;
- execution evaluation, retry and replanning;
- human approval before high-impact application actions;
- WebSocket task trace for observability.

## Runtime architecture

```text
Browser / UI
    |
    v
FastAPI ---------------------------------------------------+
    |                                                      |
    | REST                                                 | WebSocket trace
    v                                                      |
Task / Job APIs                                            |
    |                                                      |
    v                                                      |
SQLite <----------- Trace / Task / Job state --------------+
    ^
    |
LangGraph Workflow
    |
    +--> prepare
    +--> Browser Use Agent
    +--> evaluator
    |       +--> pass -> finish
    |       +--> retryable -> replanner -> Browser Agent
    +--> persist result / evaluation
```

## Agent state machine

```text
START -> prepare -> execute -> evaluate -> finish -> END
                         ^          |
                         |          | retryable
                         +-- replan-+
```

`AGENT_MAX_RETRIES` caps retry loops. The evaluator uses task success, final result presence, action history, errors, step count and duration as auditable signals.

## Job discovery and deduplication

For `job_search` tasks Browser Use is configured with `output_model_schema=DiscoveredJobs`. A SHA-256 fingerprint from normalized title/company/location/url prevents duplicate rows.

## Resume matching

V0.2 combines explicit skill evidence and embedding similarity. OpenAI-compatible embeddings are used when configured; deterministic signed feature hashing is used in offline demo mode.

```text
final_score = 0.70 * skill_score + 0.30 * semantic_score
```

## Human-in-the-loop

`application` tasks always require explicit approval. The agent must not invent candidate information, bypass access controls, or guess ambiguous fields.

## Observability

Trace events include task creation, approval, graph preparation, agent attempts, action history, job ingestion, evaluation, replanning and final workflow state. `/ws/tasks/{task_id}` streams them to the UI.

## Production roadmap

- PostgreSQL + pgvector/Qdrant
- multi-source connectors and scheduled discovery
- authenticated browser profiles
- LangGraph checkpointer for durable execution
- reranking model
- OpenTelemetry / LangSmith-compatible tracing
- evaluation dataset and regression benchmark
- queue worker instead of in-process BackgroundTasks
