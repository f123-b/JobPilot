from __future__ import annotations

import asyncio
from typing import Any

from .. import db
from ..agents.planner import heuristic_plan
from ..schemas import BrowserRunResult
from ..services.agent_evaluation import evaluate_run
from ..services.failure_classifier import classify_failure

BENCHMARK_VERSION = "v0.4-core-1"


def _case(name: str, passed: bool, detail: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


async def run_core_benchmark(*, persist: bool = True) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []

    search_plan = heuristic_plan({
        "objective": "Find AI Agent jobs in Shanghai",
        "task_type": "job_search",
        "payload": {"resume_text": "Python LangGraph RAG FastAPI"},
    })
    agents = [x.agent for x in search_plan.steps]
    cases.append(_case("planner_job_search", agents == ["resume", "search", "ranking", "evaluate"], {"agents": agents}))

    application_plan = heuristic_plan({
        "objective": "Prepare this application safely",
        "task_type": "application",
        "payload": {"resume_text": "Python developer"},
    })
    app_agents = [x.agent for x in application_plan.steps]
    cases.append(_case("planner_application", app_agents == ["resume", "browser", "evaluate"], {"agents": app_agents}))

    good_eval = evaluate_run(BrowserRunResult(success=True, final_result="done", actions=["open", "extract"], errors=[], step_count=2, duration_seconds=1.2))
    cases.append(_case("evaluator_success", good_eval.passed, good_eval.model_dump()))

    timeout = classify_failure(["navigation timeout while loading page"])
    cases.append(_case("failure_timeout", timeout.category == "timeout" and timeout.retryable, timeout.model_dump()))

    captcha = classify_failure("reCAPTCHA challenge required")
    cases.append(_case("failure_captcha", captcha.category == "captcha" and not captcha.retryable, captcha.model_dump()))

    passed_count = sum(1 for x in cases if x["passed"])
    score = round(100.0 * passed_count / max(1, len(cases)), 2)
    result = {
        "name": "jobpilot-core",
        "version": BENCHMARK_VERSION,
        "score": score,
        "passed": passed_count == len(cases),
        "cases": cases,
        "summary": {"passed": passed_count, "total": len(cases)},
    }
    if persist:
        saved = db.save_benchmark_run(result["name"], result["version"], result["score"], result["passed"], result)
        result["run_id"] = saved["id"]
    return result


if __name__ == "__main__":
    db.init_db()
    print(asyncio.run(run_core_benchmark()))
