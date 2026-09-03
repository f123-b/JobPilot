from __future__ import annotations

from typing import Any

from ..schemas import AgentPlan, AgentPlanStep
from ..services.llm import LLMUnavailable, chat_json

_ALLOWED = {"resume", "search", "ranking", "browser", "evaluate"}


def heuristic_plan(task: dict[str, Any]) -> AgentPlan:
    """Deterministic fallback so the orchestrator works without an LLM key."""
    task_type = task["task_type"]
    payload = task.get("payload", {})
    has_resume = bool((payload.get("resume_text") or "").strip())
    steps: list[AgentPlanStep] = []

    if has_resume and task_type in {"job_search", "application"}:
        steps.append(AgentPlanStep(agent="resume", objective="Extract an evidence-grounded candidate profile from the supplied resume."))

    if task_type == "job_search":
        steps.append(AgentPlanStep(agent="search", objective=task["objective"]))
        if has_resume:
            steps.append(AgentPlanStep(agent="ranking", objective="Rank discovered jobs against the candidate resume using evidence and semantic similarity."))
    else:
        steps.append(AgentPlanStep(agent="browser", objective=task["objective"]))

    steps.append(AgentPlanStep(agent="evaluate", objective="Evaluate whether the execution result is complete, auditable and safe."))
    return AgentPlan(
        goal=task["objective"],
        rationale=f"Deterministic plan for task_type={task_type}; side-effect boundaries remain enforced by the outer approval gate.",
        steps=steps,
        planner_backend="heuristic",
    )


async def build_plan(task: dict[str, Any]) -> AgentPlan:
    fallback = heuristic_plan(task)
    system = """You are the planner for JobPilot, a job-search multi-agent system.
Return JSON only with: goal, rationale, steps.
Each step must contain agent and objective. Allowed agents: resume, search, ranking, browser, evaluate.
Rules:
- job_search should use search; use resume + ranking only when resume_text exists.
- research/application should use browser rather than search.
- evaluate must be the last step.
- Never add an agent that is unrelated to the user's task.
- Do not bypass the human-approval gate for application tasks."""
    prompt = (
        f"task_type={task['task_type']}\nobjective={task['objective']}\n"
        f"resume_present={bool((task.get('payload', {}).get('resume_text') or '').strip())}\n"
        f"job_url={task.get('payload', {}).get('job_url') or ''}"
    )
    try:
        data = await chat_json(system, prompt)
        raw_steps = data.get("steps") or []
        cleaned: list[AgentPlanStep] = []
        for step in raw_steps[:8]:
            agent = str(step.get("agent", "")).strip().lower()
            objective = str(step.get("objective", "")).strip()
            if agent in _ALLOWED and objective:
                cleaned.append(AgentPlanStep(agent=agent, objective=objective))
        # Canonicalize ordering after LLM planning. The model may refine objectives but cannot
        # introduce unsafe or semantically invalid execution routes.
        objective_by_agent = {step.agent: step.objective for step in cleaned}
        task_type = task["task_type"]
        has_resume = bool((task.get("payload", {}).get("resume_text") or "").strip())
        canonical_agents: list[str] = []
        if has_resume and task_type in {"job_search", "application"}:
            canonical_agents.append("resume")
        if task_type == "job_search":
            canonical_agents.append("search")
            if has_resume:
                canonical_agents.append("ranking")
        else:
            canonical_agents.append("browser")
        canonical_agents.append("evaluate")

        fallback_objective = {step.agent: step.objective for step in fallback.steps}
        canonical = [
            AgentPlanStep(
                agent=agent,  # type: ignore[arg-type]
                objective=objective_by_agent.get(agent) or fallback_objective.get(agent) or task["objective"],
            )
            for agent in canonical_agents
        ]
        return AgentPlan(
            goal=str(data.get("goal") or task["objective"]),
            rationale=str(data.get("rationale") or "LLM generated execution plan."),
            steps=canonical,
            planner_backend="llm",
        )
    except (LLMUnavailable, Exception):
        return fallback
