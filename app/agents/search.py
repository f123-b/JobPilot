from __future__ import annotations

from typing import Any

from ..schemas import BrowserRunResult
from ..services.browser_agent import run_browser_agent


async def run_search_agent(task: dict[str, Any], objective: str) -> BrowserRunResult:
    """Search specialist. Browser Use remains the execution engine, but the role is isolated."""
    search_task = dict(task)
    search_task["task_type"] = "job_search"
    return await run_browser_agent(search_task, objective)
