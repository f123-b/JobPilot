# JobPilot

AI Job Search & Browser Agent built for agent-engineering practice and portfolio use.

**V0.2** upgrades the MVP into a real workflow: **LangGraph orchestration + Browser Use + structured job discovery + deduplication + embedding matching + evaluation/replanning + Human-in-the-loop + WebSocket trace**.

## Features

- **JD Parser** — structured extraction with LLM and offline heuristic fallback.
- **Resume/JD Matching** — explicit skill coverage + embedding similarity; no fabricated experience.
- **Browser Agent** — Browser Use task execution for research, job discovery and approved applications.
- **Structured Job Search** — `output_model_schema` produces typed job records that are persisted automatically.
- **Job Deduplication** — stable fingerprint prevents repeated listings from polluting the database.
- **LangGraph Workflow** — prepare → execute → evaluate → retry/replan → finish.
- **Agent Evaluation** — quality score from success/result/actions/errors/steps/duration.
- **Human-in-the-loop** — application tasks always require explicit approval.
- **Live Trace** — WebSocket task timeline in the UI.
- **Offline Demo Mode** — parser and matching still work without API keys.

## Architecture

```text
User
 |
FastAPI + Web UI
 |
LangGraph Agent Workflow
 |-- Prepare
 |-- Browser Use Agent
 |-- Evaluation
 |-- Replan / Retry
 |-- Finish
 |
 +----> SQLite Task + Trace
 +----> Deduplicated Job Store

Resume + JD
 |
Skill Evidence + Embedding Similarity
 |
Explainable Match Result
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for details.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`.

### Optional API configuration

Use Browser Use Cloud:

```env
BROWSER_USE_API_KEY=...
BROWSER_MODEL=bu-2-0-mini-preview
```

Or an OpenAI-compatible provider:

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=
LLM_MODEL=gpt-5-mini
EMBEDDING_MODEL=text-embedding-3-small
```

Without keys, JD parsing and matching remain available in offline fallback mode. Browser execution requires a configured LLM.

## API

### Parse JD

```http
POST /api/jd/parse
```

### Match resume and JD

```http
POST /api/match
```

Returns total score plus `skill_score` and `semantic_score`.

### Ingest jobs

```http
POST /api/jobs/ingest
```

Duplicate listings are merged via a stable fingerprint.

### Create Browser Agent task

```http
POST /api/tasks
```

Task types:

- `job_search`
- `research`
- `application`

### Approve task

```http
POST /api/tasks/{task_id}/approve
```

### Live trace

```text
ws://127.0.0.1:8000/ws/tasks/{task_id}
```

## Agent safety boundaries

JobPilot does not attempt to bypass CAPTCHAs or access controls. It does not invent candidate information. Application tasks are gated by explicit Human-in-the-loop approval, and ambiguous fields should stop submission rather than be guessed.

## Tests

```bash
pytest -q
```

The unit suite covers offline matching, deduplication, evaluation and replanning logic without requiring browser credentials.

## Resume-ready talking points

- Used **LangGraph StateGraph** to model an auditable agent lifecycle and conditional retry loop.
- Integrated **Browser Use structured output** to turn browser observations into typed job records.
- Built **Skill + Embedding hybrid ranking** with an offline deterministic fallback.
- Added an **Agent Evaluation** layer and **replanning** rather than treating a completed LLM call as success.
- Added **Human-in-the-loop** controls for high-impact external actions.
- Implemented **WebSocket trace** and persistent execution history for debugging and evaluation.

## Roadmap

- PostgreSQL + pgvector/Qdrant
- durable LangGraph checkpointing
- multi-source scheduled job discovery
- authenticated browser profiles
- reranking + personalized search policy
- benchmark dataset and Agent regression evaluation
- worker queue / distributed execution
