# JobPilot

**JobPilot V0.4.0** is a portfolio-oriented AI job-search Agent platform built around LangGraph orchestration, Browser Use, Resume RAG, long-term memory and a production-style execution runtime.

V0.4 moves execution out of FastAPI background execution into a **durable queue + worker** model and adds PostgreSQL application storage, Token/cost accounting, failure taxonomy, an offline Agent benchmark, OpenTelemetry integration and CI.

## Core capabilities

- **Planner + Multi-Agent LangGraph** — Planner, Resume, Search, Ranking, Browser and Evaluation agents.
- **Human-in-the-loop** — application tasks cannot execute before explicit approval.
- **Browser Agent** — Browser Use for search/research/approved application execution.
- **Resume RAG** — TXT/MD/PDF/DOCX parsing, section-aware chunks, embeddings and JD-specific evidence retrieval.
- **Vector memory** — pgvector in production; SQLite cosine-search fallback locally.
- **Long-term memory** — user preferences plus job lifecycle state.
- **Persistent LangGraph checkpoints** — PostgreSQL or SQLite checkpointer with stable `workflow_thread_id`.
- **Durable task queue** — worker leases, delayed retry and dead-letter state.
- **PostgreSQL application DB** — jobs, tasks, traces, memory, queue, usage and benchmarks can share PostgreSQL.
- **Usage / cost accounting** — LLM and embedding tokens, browser duration/steps, configurable cost estimation.
- **Failure taxonomy** — timeout/network/rate-limit/captcha/auth/element/model/validation/safety categories.
- **Agent Benchmark** — deterministic offline regression suite persisted to `benchmark_runs`.
- **Observability** — database-backed metrics + optional OpenTelemetry traces.
- **CI** — Python 3.11/3.13 compile, tests and offline benchmark in GitHub Actions.

## Architecture

```text
Web UI / API
     |
   FastAPI
     |
 durable task_queue
     |
 worker claim + lease
     |
 LangGraph Planner
     |
 Resume / Search / Ranking / Browser
     |
 Evaluation -> pass / replan
     |
 terminal state

Persistence:
  PostgreSQL -> app data, queue, usage, benchmark
  pgvector   -> Resume RAG
  Checkpointer -> LangGraph workflow state

Local fallback:
  SQLite app DB + SQLite vector store + SQLite checkpointer
```

## Durable execution

```text
POST /api/tasks
      |
persist task
      |
enqueue
      |
worker claim + lease
      |
LangGraph workflow
      |
      +-- success -> done
      +-- agent failure -> Evaluate / Replan
      +-- runtime failure -> delayed retry / dead
```

Application tasks stay at `waiting_approval` until Human-in-the-loop approval.

## Token / cost accounting

Provider-reported LLM/embedding usage is persisted in `usage_events`; Browser tasks record duration, steps, actions and errors. Prices are configuration-driven:

```env
LLM_INPUT_COST_PER_1M=0
LLM_OUTPUT_COST_PER_1M=0
EMBEDDING_COST_PER_1M=0
```

JobPilot intentionally does not hard-code provider prices.

## Quick start

Python 3.11+:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

The embedded worker is enabled by default in local mode.

## Production-style Docker stack

```bash
cp .env.example .env
docker compose up --build
```

The stack starts PostgreSQL+pgvector, the FastAPI web process and an independent queue worker.

## Main APIs

Agent/task:
- `POST /api/plan`
- `POST /api/tasks`
- `POST /api/tasks/{id}/approve`
- `POST /api/tasks/{id}/resume`
- `GET /api/tasks/{id}`
- `GET /api/tasks`

RAG/memory:
- `POST /api/resume/index`
- `POST /api/resume/search`
- `GET /api/memory/users/{user_id}`
- `PUT /api/memory/users/{user_id}/{key}`
- `POST /api/memory/jobs`

Operations/evaluation:
- `GET /api/queue`
- `GET /api/metrics/summary`
- `GET /api/tasks/{id}/usage`
- `POST /api/benchmarks/run`
- `GET /api/benchmarks`

## Offline benchmark

```bash
python -m app.evaluation.benchmark
```

The deterministic core benchmark covers Planner routing, safe application routing, quality-gate behavior and failure classification.

## Tests

```bash
pytest -q
```

## Repository map

```text
app/
├── agents/              # Planner / Resume / Search / Ranking / Browser
├── evaluation/          # Agent benchmark
├── memory/              # long-term memory
├── observability/       # OpenTelemetry integration
├── rag/                 # parsing / chunking / vector retrieval
├── runtime/             # durable worker
├── services/            # LLM, embeddings, usage, failure taxonomy
├── storage/             # SQLite/PostgreSQL persistence and queue
├── workflow/            # LangGraph orchestration + checkpoints
├── db.py                # compatibility facade
└── main.py              # FastAPI

benchmarks/
docs/
.github/workflows/
```

## Validation boundary

Automated tests validate the SQLite/local path without external services. PostgreSQL/pgvector, live Browser Use and OTLP export require their corresponding external service/credentials and should be verified in an integration deployment before claiming production SLOs.
