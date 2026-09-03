from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

try:
    from langgraph.graph import END, START, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:  # keep offline tests/imports usable
    END = START = StateGraph = None  # type: ignore[assignment]
    LANGGRAPH_AVAILABLE = False

from .. import db
from ..agents.browser import run_execution_agent
from ..agents.planner import build_plan
from ..agents.ranking import rank_candidates
from ..agents.resume import build_resume_profile
from ..agents.search import run_search_agent
from ..config import settings
from ..schemas import AgentPlanStep, BrowserRunResult, JobCandidate, RankedJob
from ..services.agent_evaluation import evaluate_run
from ..services.job_store import ingest_candidates
from ..services.replanner import replan_objective

AgentName = Literal["resume", "search", "ranking", "browser", "evaluate", "finish"]


class MultiAgentState(TypedDict, total=False):
    task_id: int
    task: dict[str, Any]
    attempt: int
    plan: dict[str, Any]
    remaining_steps: list[dict[str, Any]]
    current_agent: str | None
    resume_profile: dict[str, Any]
    run: dict[str, Any]
    candidates: list[dict[str, Any]]
    ranked_jobs: list[dict[str, Any]]
    evaluation: dict[str, Any]
    final_status: str


def _current_step(state: MultiAgentState, expected: str) -> tuple[str, list[dict[str, Any]]]:
    steps = list(state.get("remaining_steps", []))
    if not steps:
        return state.get("task", {}).get("objective", ""), []
    step = steps[0]
    if step.get("agent") != expected:
        raise RuntimeError(f"workflow route mismatch: expected {expected}, got {step.get('agent')}")
    return str(step.get("objective") or state["task"]["objective"]), steps[1:]


def _route_next(state: MultiAgentState) -> AgentName:
    steps = state.get("remaining_steps", [])
    if not steps:
        return "finish"
    agent = str(steps[0].get("agent") or "")
    if agent not in {"resume", "search", "ranking", "browser", "evaluate"}:
        raise RuntimeError(f"unknown agent in plan: {agent}")
    return agent  # type: ignore[return-value]


def _workflow_snapshot(state: MultiAgentState, *, current_agent: str | None = None, remaining_steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "attempt": state.get("attempt", 0),
        "current_agent": current_agent if current_agent is not None else state.get("current_agent"),
        "remaining_agents": [x.get("agent") for x in (remaining_steps if remaining_steps is not None else state.get("remaining_steps", []))],
        "candidate_count": len(state.get("candidates", [])),
        "ranked_count": len(state.get("ranked_jobs", [])),
    }


def _set_agent(task_id: int, agent: str, state: MultiAgentState, remaining: list[dict[str, Any]]) -> None:
    db.update_task(task_id, current_agent=agent, workflow=_workflow_snapshot(state, current_agent=agent, remaining_steps=remaining))
    db.add_trace(task_id, "agent_handoff", {"agent": agent, "remaining_agents": [x.get("agent") for x in remaining]})


async def prepare_node(state: MultiAgentState) -> MultiAgentState:
    task = db.get_task(state["task_id"])
    if not task:
        raise RuntimeError("task not found")
    if task["requires_approval"] and task["approved"] is not True:
        raise RuntimeError("approval required")
    db.update_task(
        task["id"],
        status="running",
        error_text=None,
        current_agent="planner",
        workflow={"attempt": 0, "current_agent": "planner", "remaining_agents": []},
    )
    db.add_trace(task["id"], "graph_prepare", {"workflow": "multi-agent-v0.3", "thread_id": task.get("workflow_thread_id")})
    return {"task": task, "attempt": 0, "current_agent": "planner"}


async def planner_node(state: MultiAgentState) -> MultiAgentState:
    task = state["task"]
    plan = await build_plan(task)
    steps = [step.model_dump() for step in plan.steps]
    db.update_task(task["id"], plan=plan.model_dump(), current_agent="planner", workflow={
        "attempt": state.get("attempt", 0),
        "current_agent": "planner",
        "remaining_agents": [x["agent"] for x in steps],
    })
    db.add_trace(task["id"], "planner_plan", {
        "backend": plan.planner_backend,
        "goal": plan.goal,
        "rationale": plan.rationale,
        "agents": [x.agent for x in plan.steps],
        "steps": steps,
    })
    return {"plan": plan.model_dump(), "remaining_steps": steps, "current_agent": "planner"}


async def resume_node(state: MultiAgentState) -> MultiAgentState:
    objective, remaining = _current_step(state, "resume")
    task = state["task"]
    _set_agent(task["id"], "resume", state, remaining)
    resume_text = str(task.get("payload", {}).get("resume_text") or "")
    profile = build_resume_profile(resume_text)
    db.add_trace(task["id"], "resume_agent_result", {
        "objective": objective,
        "skills": profile.skills,
        "evidence_count": len(profile.evidence),
        "experience_years": profile.experience_years,
    })
    return {"resume_profile": profile.model_dump(), "remaining_steps": remaining, "current_agent": "resume"}


async def search_node(state: MultiAgentState) -> MultiAgentState:
    objective, remaining = _current_step(state, "search")
    task = state["task"]
    _set_agent(task["id"], "search", state, remaining)
    db.add_trace(task["id"], "search_agent_start", {"attempt": state.get("attempt", 0) + 1, "objective": objective[:1400]})
    run = await run_search_agent(task, objective)
    candidates = [x.model_dump() for x in run.discovered_jobs]
    ingest_summary: dict[str, Any] = {"received": 0, "inserted": 0, "deduplicated": 0}
    if run.discovered_jobs:
        ingest_summary = ingest_candidates(run.discovered_jobs)
    db.add_trace(task["id"], "search_agent_result", {
        "success": run.success,
        "candidate_count": len(candidates),
        "step_count": run.step_count,
        "error_count": len([x for x in run.errors if x]),
        "ingest": {k: v for k, v in ingest_summary.items() if k != "jobs"},
    })
    db.update_task(task["id"], workflow={
        "attempt": state.get("attempt", 0),
        "current_agent": "search",
        "remaining_agents": [x.get("agent") for x in remaining],
        "candidate_count": len(candidates),
        "ranked_count": len(state.get("ranked_jobs", [])),
    })
    return {"run": run.model_dump(), "candidates": candidates, "remaining_steps": remaining, "current_agent": "search"}


async def ranking_node(state: MultiAgentState) -> MultiAgentState:
    objective, remaining = _current_step(state, "ranking")
    task = state["task"]
    _set_agent(task["id"], "ranking", state, remaining)
    candidates = [JobCandidate.model_validate(x) for x in state.get("candidates", [])]
    resume_text = str(task.get("payload", {}).get("resume_text") or "")
    ranked = await rank_candidates(candidates, resume_text)
    payload = [x.model_dump() for x in ranked]
    db.add_trace(task["id"], "ranking_agent_result", {
        "objective": objective,
        "ranked_count": len(ranked),
        "top_jobs": [
            {"title": x.job.title, "company": x.job.company, "score": x.score, "url": x.job.url}
            for x in ranked[:8]
        ],
    })
    db.update_task(task["id"], workflow={
        "attempt": state.get("attempt", 0),
        "current_agent": "ranking",
        "remaining_agents": [x.get("agent") for x in remaining],
        "candidate_count": len(candidates),
        "ranked_count": len(ranked),
    })
    return {"ranked_jobs": payload, "remaining_steps": remaining, "current_agent": "ranking"}


async def browser_node(state: MultiAgentState) -> MultiAgentState:
    objective, remaining = _current_step(state, "browser")
    task = state["task"]
    _set_agent(task["id"], "browser", state, remaining)
    db.add_trace(task["id"], "browser_agent_start", {"attempt": state.get("attempt", 0) + 1, "objective": objective[:1400]})
    run = await run_execution_agent(task, objective)
    db.add_trace(task["id"], "browser_agent_result", {
        "success": run.success,
        "actions": run.actions,
        "errors": run.errors,
        "urls": run.urls,
        "step_count": run.step_count,
        "duration_seconds": run.duration_seconds,
    })
    return {"run": run.model_dump(), "remaining_steps": remaining, "current_agent": "browser"}


async def evaluate_node(state: MultiAgentState) -> MultiAgentState:
    _, remaining = _current_step(state, "evaluate")
    task = state["task"]
    _set_agent(task["id"], "evaluate", state, remaining)
    if "run" not in state:
        raise RuntimeError("evaluate agent requires an execution result")
    run = BrowserRunResult.model_validate(state["run"])
    evaluation = evaluate_run(run)

    # Job-search quality should reflect whether the search produced usable candidates.
    if task["task_type"] == "job_search" and not state.get("candidates"):
        evaluation.score = max(0, evaluation.score - 25)
        evaluation.passed = False
        evaluation.reasons.append("Search Agent did not produce structured job candidates")
        if run.success is not False:
            evaluation.retryable = True

    db.update_task(task["id"], evaluation=evaluation.model_dump(), workflow={
        "attempt": state.get("attempt", 0),
        "current_agent": "evaluate",
        "remaining_agents": [],
        "candidate_count": len(state.get("candidates", [])),
        "ranked_count": len(state.get("ranked_jobs", [])),
    })
    db.add_trace(task["id"], "evaluation", evaluation.model_dump())
    return {"evaluation": evaluation.model_dump(), "remaining_steps": remaining, "current_agent": "evaluate"}


def route_after_evaluation(state: MultiAgentState) -> Literal["replan", "finish"]:
    evaluation = state["evaluation"]
    attempt = state.get("attempt", 0)
    if evaluation["passed"]:
        return "finish"
    if evaluation["retryable"] and attempt < settings.agent_max_retries:
        return "replan"
    return "finish"


async def replan_node(state: MultiAgentState) -> MultiAgentState:
    task = state["task"]
    run = BrowserRunResult.model_validate(state["run"])
    next_attempt = state.get("attempt", 0) + 1
    objective = replan_objective(task["objective"], run, next_attempt + 1)
    steps: list[AgentPlanStep]
    if task["task_type"] == "job_search":
        steps = [AgentPlanStep(agent="search", objective=objective)]
        if (task.get("payload", {}).get("resume_text") or "").strip():
            steps.append(AgentPlanStep(agent="ranking", objective="Re-rank the refreshed candidate set against the resume."))
    else:
        steps = [AgentPlanStep(agent="browser", objective=objective)]
    steps.append(AgentPlanStep(agent="evaluate", objective="Re-evaluate the retried execution result."))
    remaining = [x.model_dump() for x in steps]
    db.update_task(task["id"], retry_count=next_attempt, current_agent="planner", workflow={
        "attempt": next_attempt,
        "current_agent": "planner",
        "remaining_agents": [x.agent for x in steps],
        "candidate_count": len(state.get("candidates", [])),
        "ranked_count": len(state.get("ranked_jobs", [])),
    })
    db.add_trace(task["id"], "planner_replan", {
        "retry_count": next_attempt,
        "reason": state.get("evaluation", {}).get("reasons", []),
        "new_objective": objective[:1400],
        "agents": [x.agent for x in steps],
    })
    return {"attempt": next_attempt, "remaining_steps": remaining, "current_agent": "planner"}


def _result_text(state: MultiAgentState) -> str:
    ranked = [RankedJob.model_validate(x) for x in state.get("ranked_jobs", [])]
    run = BrowserRunResult.model_validate(state.get("run", {}))
    if ranked:
        top = [
            {
                "title": item.job.title,
                "company": item.job.company,
                "location": item.job.location,
                "score": item.score,
                "url": item.job.url,
                "matched_skills": item.matched_skills[:8],
                "missing_skills": item.missing_skills[:6],
            }
            for item in ranked[:10]
        ]
        return json.dumps({"summary": run.final_result, "top_ranked_jobs": top}, ensure_ascii=False, indent=2)
    return run.final_result


async def finish_node(state: MultiAgentState) -> MultiAgentState:
    task = state["task"]
    evaluation = state.get("evaluation") or {"passed": False, "score": 0}
    status = "completed" if evaluation.get("passed") else "failed"
    run = BrowserRunResult.model_validate(state.get("run", {}))
    result_text = _result_text(state)
    errors = [str(x) for x in run.errors if x]
    db.update_task(
        task["id"],
        status=status,
        current_agent=None,
        result_text=result_text,
        error_text=None if status == "completed" else "; ".join(errors)[:4000] or "evaluation failed",
        workflow={
            "attempt": state.get("attempt", 0),
            "current_agent": None,
            "remaining_agents": [],
            "candidate_count": len(state.get("candidates", [])),
            "ranked_count": len(state.get("ranked_jobs", [])),
        },
    )
    db.add_trace(task["id"], "graph_finish", {
        "status": status,
        "score": evaluation.get("score", 0),
        "attempts": state.get("attempt", 0) + 1,
        "ranked_count": len(state.get("ranked_jobs", [])),
    })
    return {"final_status": status, "current_agent": None}


def build_multi_agent_graph():
    if not LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed; run pip install -r requirements.txt")

    graph = StateGraph(MultiAgentState)
    graph.add_node("prepare", prepare_node)
    graph.add_node("planner", planner_node)
    graph.add_node("resume", resume_node)
    graph.add_node("search", search_node)
    graph.add_node("ranking", ranking_node)
    graph.add_node("browser", browser_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("replan", replan_node)
    graph.add_node("finish", finish_node)

    routes = {"resume": "resume", "search": "search", "ranking": "ranking", "browser": "browser", "evaluate": "evaluate", "finish": "finish"}
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "planner")
    graph.add_conditional_edges("planner", _route_next, routes)
    for name in ("resume", "search", "ranking", "browser"):
        graph.add_conditional_edges(name, _route_next, routes)
    graph.add_conditional_edges("evaluate", route_after_evaluation, {"replan": "replan", "finish": "finish"})
    graph.add_conditional_edges("replan", _route_next, routes)
    graph.add_edge("finish", END)
    return graph.compile()


async def _fallback_workflow(task_id: int) -> None:
    """Same state machine for environments where LangGraph is not installed."""
    state: MultiAgentState = {"task_id": task_id}
    state.update(await prepare_node(state))
    state.update(await planner_node(state))

    handlers = {
        "resume": resume_node,
        "search": search_node,
        "ranking": ranking_node,
        "browser": browser_node,
        "evaluate": evaluate_node,
    }
    while True:
        agent = _route_next(state)
        if agent == "finish":
            break
        state.update(await handlers[agent](state))
        if agent == "evaluate":
            route = route_after_evaluation(state)
            if route == "replan":
                state.update(await replan_node(state))
                continue
            break
    state.update(await finish_node(state))


async def execute_multi_agent_workflow(task_id: int) -> None:
    try:
        if LANGGRAPH_AVAILABLE:
            graph = build_multi_agent_graph()
            await graph.ainvoke(
                {"task_id": task_id},
                {"configurable": {"thread_id": f"jobpilot-task-{task_id}"}},
            )
        else:
            await _fallback_workflow(task_id)
    except Exception as exc:
        db.update_task(task_id, status="failed", current_agent=None, error_text=str(exc))
        db.add_trace(task_id, "workflow_error", {"error": str(exc)})
