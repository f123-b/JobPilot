# JobPilot V0.4 Production Runtime

V0.4 separates **API admission** from **Agent execution** and adds durable state for operations, evaluation and cost accounting.

## Runtime topology

```text
Browser / API client
        |
        v
      FastAPI
        |
        +---- tasks / approval / metrics
        |
        v
 PostgreSQL task_queue
        |
   lease + claim
        |
        v
  Worker process
        |
        v
 LangGraph workflow
        |
 +------+------+------+------+
 |             |             |
LLM       Browser Use    Resume RAG
 |             |             |
 +-------------+-------------+
               |
        usage + traces
               |
          PostgreSQL
```

`docker-compose.yml` runs the web API and worker as separate containers. The API sets `WORKER_ENABLED=false`; the worker consumes the shared PostgreSQL queue with `python -m app.runtime.worker_main`.

## Durable queue semantics

`task_queue` stores status, availability, worker ownership, lease expiry, attempts and last error. SQLite uses `BEGIN IMMEDIATE` for a single-host atomic claim. PostgreSQL uses `FOR UPDATE SKIP LOCKED`, allowing multiple worker replicas to claim different jobs without duplicate execution.

Agent-level recoverable failures remain inside LangGraph (`Evaluate -> Replan`). Worker retries are reserved for runtime/infrastructure failures.

## PostgreSQL application database

```env
DATABASE_BACKEND=postgres
DATABASE_URL=postgresql://jobpilot:jobpilot@postgres:5432/jobpilot
```

The V0.4 storage layer uses PostgreSQL for jobs, tasks, traces, user/job memory, queue state, usage accounting and benchmark runs. Resume vectors and LangGraph checkpoints can use the same PostgreSQL instance via `POSTGRES_URL`. SQLite remains the local fallback used by the offline test suite.

## Token and cost accounting

`usage_events` records component, model, input/output/total tokens, estimated USD cost, duration and component metadata. OpenAI-compatible chat and embedding calls read provider usage metadata. Browser execution records duration, steps, actions and errors when model token counts are unavailable.

Pricing is configuration-driven:

```env
LLM_INPUT_COST_PER_1M=0
LLM_OUTPUT_COST_PER_1M=0
EMBEDDING_COST_PER_1M=0
```

## Failure taxonomy

Current categories: `captcha`, `auth`, `rate_limit`, `timeout`, `network`, `element`, `safety_block`, `validation`, `model`, `unknown`.

## OpenTelemetry

```env
OTEL_ENABLED=true
OTEL_SERVICE_NAME=jobpilot
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

When enabled, FastAPI and worker execution emit traces. When disabled, JobPilot still exposes database-backed operational metrics.

## Operational APIs

- `GET /api/queue`
- `GET /api/metrics/summary`
- `GET /api/tasks/{id}/usage`
- `POST /api/benchmarks/run`
- `GET /api/benchmarks`

## Validation boundary

The repository test suite validates the SQLite/local path and queue semantics without external services. PostgreSQL/pgvector, OTLP export and live Browser Use require external services/credentials and should be exercised in integration deployments.
