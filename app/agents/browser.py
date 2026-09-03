from __future__ import annotations

from typing import Any

from ..schemas import BrowserRunResult
from ..services.browser_agent import run_browser_agent


async def run_execution_agent(task: dict[str, Any], objective: str) -> BrowserRunResult:
    """Browser specialist for research and approved application tasks."""
    return await run_browser_agent(task, objective)
