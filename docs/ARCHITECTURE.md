# JobPilot V0.3-1 Architecture

## 1. Goal

V0.3-1 converts JobPilot from a single browser-execution graph into a role-separated multi-agent runtime. The main design requirement is not merely "more agents"; each specialist owns a distinct responsibility and the parent graph controls handoffs, retries and safety boundaries.

Specialists:

- **Planner Agent** — task decomposition and objective refinement;
- **Resume Agent** — evidence-grounded candidate profile extraction;
- **Search Agent** — structured job discovery;
- **Ranking Agent** — resume/job scoring;
- **Browser Agent** — research or approved application execution;
- **Evaluation Agent** — quality gate and retry decision.

## 2. Parent graph

```text
START
  |
prepare
  |
planner
  |
  +-- job_search + resume --> resume --> search --> ranking --> evaluate
  |
  +-- job_search ----------> search -----------> evaluate
  |
  +-- research ------------> browser ----------> evaluate
  |
  +-- application + resume -> resume --> browser -> evaluate
  |
  +-- application ---------> browser ----------> evaluate
                                                   |
                                  +----------------+---------------+
                                  |                                |
                                pass                           retryable
                                  |                                |
                                  v                                v
                                finish                           replan
                                  |                                |
                                 END               search/browser branch only
                                                                   |
                                                               evaluate
```

`AGENT_MAX_RETRIES` limits replanning loops.

## 3. Planner design

The Planner has two backends:

1. `llm` — produces a structured plan when an OpenAI-compatible model is configured;
2. `heuristic` — deterministic fallback for local/demo operation.

The LLM does not have final authority over the execution route. Its output is canonicalized using `task_type` and resume availability:

```text
job_search + resume -> resume, search, ranking, evaluate
job_search          -> search, evaluate
research            -> browser, evaluate
application + resume-> resume, browser, evaluate
application         -> browser, evaluate
```

This design separates **agentic objective planning** from **deterministic safety policy**.

## 4. Shared graph state

The LangGraph state includes:

```text
task_id
task
attempt
plan
remaining_steps
current_agent
resume_profile
run
candidates
ranked_jobs
evaluation
final_status
```

The SQLite `tasks` table separately persists:

```text
plan_json
workflow_json
current_agent
workflow_thread_id
retry_count
evaluation_json
```

`workflow_thread_id` is introduced now so V0.3-2 can attach a persistent LangGraph checkpointer without changing the task identity model.

## 5. Agent responsibilities

### Planner Agent

Inputs:

- objective;
- task type;
- resume presence;
- target URL.

Outputs:

- `AgentPlan.goal`;
- rationale;
- ordered typed `AgentPlanStep[]`.

### Resume Agent

V0.3-1 intentionally does **not** claim full RAG. It extracts conservative, explicit resume evidence:

- recognized skills;
- verbatim evidence snippets;
- simple experience-year hints;
- keywords.

V0.3-2 will replace/extend this with chunk-level vector retrieval.

### Search Agent

Search uses Browser Use as the browser execution engine but is isolated as a specialist role. It must return `DiscoveredJobs`, which is converted to typed `JobCandidate` objects and deduplicated into SQLite.

### Ranking Agent

For bulk ranking, V0.3-1 uses the deterministic hybrid matcher rather than one LLM call per job:

```text
score = 0.70 * explicit_skill_score + 0.30 * embedding_similarity
```

This keeps cost bounded and ranking reproducible. The direct `/api/match` endpoint may still use an LLM to calibrate a single resume/JD comparison.

### Browser Agent

Used for:

- general web research;
- approved application tasks.

Application guardrails remain enforced in the Browser prompt and, more importantly, by the outer approval gate before the graph starts.

### Evaluation Agent

The evaluator considers:

- Browser success flag;
- final-result presence;
- action history;
- errors;
- step count;
- duration;
- structured job-candidate count for `job_search`.

A `job_search` run with no structured candidates is forced to fail the quality gate even if the browser call itself returned a nominal success.

## 6. Targeted replanning

V0.2 retried the generic Browser Agent. V0.3-1 replans the failed branch:

```text
job_search failure
  -> Search Agent
  -> Ranking Agent (if resume exists)
  -> Evaluation Agent

research/application failure
  -> Browser Agent
  -> Evaluation Agent
```

Completed Resume extraction does not need to run again during a transient browser retry.

## 7. Observability

New trace events include:

- `planner_plan`
- `agent_handoff`
- `resume_agent_result`
- `search_agent_start`
- `search_agent_result`
- `ranking_agent_result`
- `browser_agent_start`
- `browser_agent_result`
- `evaluation`
- `planner_replan`
- `graph_finish`
- `workflow_error`

The WebSocket task status also streams the currently active agent and pending workflow sequence.

## 8. Human-in-the-loop

The parent task API is still the security boundary:

```text
application
   |
waiting_approval
   |
explicit approve
   |
Multi-Agent graph starts
```

Planner output cannot remove this gate because planning occurs only after `prepare_node` verifies approval.

## 9. V0.3-2 integration points

The graph is prepared for the next phase:

- replace basic Resume Agent extraction with chunked RAG;
- persist resume embeddings in pgvector/Qdrant;
- retrieve evidence snippets inside Ranking Agent;
- add long-term user/job memory;
- compile the graph with a durable LangGraph checkpointer using `workflow_thread_id`.
