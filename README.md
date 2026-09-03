# JobPilot

**JobPilot V0.3-1** is a multi-agent job-search platform built for AI application / Agent engineering practice and portfolio use.

This stage upgrades V0.2 from a single Browser Agent workflow into a **Planner-orchestrated LangGraph runtime** with specialized Resume, Search, Ranking, Browser and Evaluation agents. The system keeps Human-in-the-loop boundaries for application tasks and persists the generated plan, active agent and workflow state for observability.

## What changed in V0.3-1

- **Planner Agent** — decomposes the user goal and produces a typed execution plan. Uses an LLM when configured and a deterministic fallback otherwise.
- **Safe plan canonicalization** — the planner may refine step objectives, but cannot bypass approval or invent unrelated execution routes.
- **Resume Agent** — extracts only explicit skills and evidence snippets from supplied resume text.
- **Search Agent** — isolates structured job discovery from general browser execution.
- **Ranking Agent** — applies Skill + Embedding matching to discovered jobs and writes match scores back to the deduplicated job store.
- **Browser Agent** — handles research and approved application execution.
- **Evaluation Agent** — scores execution quality and decides finish vs. replan.
- **Planner Replan Loop** — retryable failures generate a targeted new agent sequence instead of restarting the full workflow.
- **Persistent workflow metadata** — tasks store `plan`, `current_agent`, `workflow`, `workflow_thread_id`, retry count and evaluation.
- **Live Multi-Agent Trace** — the UI shows Planner plans, agent handoffs and the currently active specialist.

Existing V0.2 capabilities remain: JD parsing, structured Browser Use output, job deduplication, hybrid resume matching, WebSocket trace, SQLite persistence and Human-in-the-loop approval.

## Runtime architecture

```text
User
 |
FastAPI + Web UI
 |
 v
Planner Agent
 |
 +---------------- task-aware plan ----------------+
 |                                                  |
 | job_search                                       | research / application
 v                                                  v
Resume Agent (optional)                       Resume Agent (optional)
 |                                                  |
 v                                                  v
Search Agent                                    Browser Agent
 |                                                  |
 v                                                  |
Ranking Agent (when resume exists)                  |
 |                                                  |
 +------------------------+-------------------------+
                          v
                    Evaluation Agent
                          |
                +---------+----------+
                |                    |
              pass                retryable
                |                    |
                v                    v
              Finish       Planner targeted replan
                                     |
                                     +--> Search/Browser -> Evaluate

SQLite
  |-- task / approval / evaluation
  |-- plan / current_agent / workflow state
  |-- trace timeline
  +-- deduplicated jobs + match score
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for node-level details.

## Agent plans

A job-search task with a resume is canonicalized to:

```text
Planner
  -> Resume Agent
  -> Search Agent
  -> Ranking Agent
  -> Evaluation Agent
```

Without a resume:

```text
Planner -> Search Agent -> Evaluation Agent
```

Research:

```text
Planner -> Browser Agent -> Evaluation Agent
```

Approved application:

```text
Planner -> Resume Agent (optional) -> Browser Agent -> Evaluation Agent
```

The Planner can change objectives for these steps, but high-impact application submission remains controlled by the outer Human-in-the-loop approval gate.

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

### Optional model configuration

Browser Use Cloud:

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

Without keys, Planner preview, JD parsing, Resume Agent extraction and resume/JD matching use deterministic local fallbacks. Real Browser Agent execution requires a configured browser-capable LLM.

## API

### Agent registry

```http
GET /api/agents
```

### Preview Planner output

```http
POST /api/plan
```

Example body:

```json
{
  "objective": "Find Shanghai AI Agent Engineer jobs and rank them against my resume",
  "task_type": "job_search",
  "resume_text": "Python, LangGraph, FastAPI, Agent, RAG...",
  "auto_execute": false
}
```

### Create Multi-Agent task

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

### Task state + trace

```http
GET /api/tasks/{task_id}
```

```text
ws://127.0.0.1:8000/ws/tasks/{task_id}
```

WebSocket status contains:

- `current_agent`
- `plan`
- `workflow`
- `retry_count`
- `evaluation`

## Safety boundaries

JobPilot does not attempt to bypass CAPTCHAs or access controls. It does not invent candidate information. Application tasks always require explicit Human-in-the-loop approval. Missing application fields should stop execution rather than be guessed.

The Planner is also constrained: its LLM output is canonicalized against the task type, so an application task cannot silently become an unapproved autonomous submission flow.

## Tests

```bash
pytest -q
```

V0.3-1 adds tests for:

- Planner agent routing;
- Resume Agent evidence extraction;
- full offline multi-agent fallback flow;
- agent handoff traces;
- Search -> Ranking -> Evaluation completion;
- existing matching, deduplication, evaluation and replanning logic.

Current local result:

```text
9 passed
```

## Resume-ready engineering points

- Built a **Planner-orchestrated Multi-Agent workflow with LangGraph StateGraph**, separating Resume, Search, Ranking, Browser and Evaluation responsibilities.
- Designed a **typed Agent Plan and deterministic safety canonicalization layer**, allowing LLM planning without giving the planner authority to bypass execution boundaries.
- Implemented **agent handoff and workflow-state persistence**, exposing current agent, pending sequence, retry count and evaluation through SQLite + WebSocket.
- Added a **targeted replanning loop** that retries only the failed Search/Browser branch instead of restarting the whole workflow.
- Implemented **hybrid ranking for discovered jobs** and persisted match scores into the deduplicated job database.
- Preserved **Human-in-the-loop** for external application side effects.

## Next stage: V0.3-2

The next stage is intentionally focused on durable knowledge and resume retrieval:

- Resume RAG Agent;
- resume/document chunking;
- pgvector or Qdrant vector store;
- evidence-level retrieval for Ranking Agent;
- user/job long-term memory;
- LangGraph persistent checkpointer for resume-after-restart execution.
