from __future__ import annotations

from typing import Any, Literal, TypedDict

try:
    from langgraph.graph import END, START, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    END = START = StateGraph = None
    LANGGRAPH_AVAILABLE = False

from .. import db
from ..config import settings
from ..schemas import BrowserRunResult
from .agent_evaluation import evaluate_run
from .browser_agent import run_browser_agent
from .job_store import ingest_candidates
from .replanner import replan_objective


class AgentState(TypedDict, total=False):
    task_id: int
    task: dict[str, Any]
    attempt: int
    objective: str
    run: dict[str, Any]
    evaluation: dict[str, Any]
    final_status: str


async def prepare_node(state: AgentState) -> AgentState:
    task = db.get_task(state["task_id"])
    if not task:
        raise RuntimeError("task not found")
    if task["requires_approval"] and task["approved"] is not True:
        raise RuntimeError("approval required")
    db.update_task(task["id"], status="running", error_text=None)
    db.add_trace(task["id"], "graph_prepare", {"workflow": "browser-agent-v0.2"})
    return {"task": task, "attempt": 0, "objective": task["objective"]}


async def execute_node(state: AgentState) -> AgentState:
    task = state["task"]
    attempt = state.get("attempt", 0)
    db.add_trace(task["id"], "agent_attempt_start", {"attempt": attempt + 1, "objective": state["objective"][:1200]})
    run = await run_browser_agent(task, state["objective"])
    db.add_trace(task["id"], "agent_history", {"attempt": attempt + 1, "success": run.success, "actions": run.actions, "errors": run.errors, "urls": run.urls, "step_count": run.step_count, "duration_seconds": run.duration_seconds})
    if run.discovered_jobs:
        ingest = ingest_candidates(run.discovered_jobs)
        db.add_trace(task["id"], "jobs_ingested", {k: v for k, v in ingest.items() if k != "jobs"})
    return {"run": run.model_dump()}


async def evaluate_node(state: AgentState) -> AgentState:
    run = BrowserRunResult.model_validate(state["run"])
    evaluation = evaluate_run(run)
    task_id = state["task"]["id"]
    db.update_task(task_id, evaluation=evaluation.model_dump())
    db.add_trace(task_id, "evaluation", evaluation.model_dump())
    return {"evaluation": evaluation.model_dump()}


def route_after_evaluation(state: AgentState) -> Literal["replan", "finish"]:
    evaluation = state["evaluation"]
    attempt = state.get("attempt", 0)
    if evaluation["passed"]:
        return "finish"
    if evaluation["retryable"] and attempt < settings.agent_max_retries:
        return "replan"
    return "finish"


async def replan_node(state: AgentState) -> AgentState:
    run = BrowserRunResult.model_validate(state["run"])
    next_attempt = state.get("attempt", 0) + 1
    objective = replan_objective(state["task"]["objective"], run, next_attempt + 1)
    task_id = state["task"]["id"]
    db.update_task(task_id, retry_count=next_attempt)
    db.add_trace(task_id, "replan", {"retry_count": next_attempt, "new_objective": objective[:1400]})
    return {"attempt": next_attempt, "objective": objective}


async def finish_node(state: AgentState) -> AgentState:
    run = BrowserRunResult.model_validate(state["run"])
    evaluation = state["evaluation"]
    task_id = state["task"]["id"]
    status = "completed" if evaluation["passed"] else "failed"
    db.update_task(task_id, status=status, result_text=run.final_result, error_text=None if status == "completed" else "; ".join(str(x) for x in run.errors if x)[:4000] or "evaluation failed")
    db.add_trace(task_id, "graph_finish", {"status": status, "score": evaluation["score"], "attempts": state.get("attempt", 0) + 1})
    return {"final_status": status}


def build_agent_graph():
    if not LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed; run pip install -r requirements.txt")
    graph = StateGraph(AgentState)
    graph.add_node("prepare", prepare_node)
    graph.add_node("execute", execute_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("replan", replan_node)
    graph.add_node("finish", finish_node)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "execute")
    graph.add_edge("execute", "evaluate")
    graph.add_conditional_edges("evaluate", route_after_evaluation, {"replan": "replan", "finish": "finish"})
    graph.add_edge("replan", "execute")
    graph.add_edge("finish", END)
    return graph.compile()


async def _fallback_workflow(task_id: int) -> None:
    state: AgentState = {"task_id": task_id}
    state.update(await prepare_node(state))
    while True:
        state.update(await execute_node(state))
        state.update(await evaluate_node(state))
        if route_after_evaluation(state) != "replan":
            break
        state.update(await replan_node(state))
    state.update(await finish_node(state))


async def execute_agent_workflow(task_id: int) -> None:
    try:
        if LANGGRAPH_AVAILABLE:
            graph = build_agent_graph()
            await graph.ainvoke({"task_id": task_id})
        else:
            await _fallback_workflow(task_id)
    except Exception as exc:
        db.update_task(task_id, status="failed", error_text=str(exc))
        db.add_trace(task_id, "workflow_error", {"error": str(exc)})
