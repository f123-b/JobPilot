from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from .. import db
from ..config import settings

_current_task_id: ContextVar[int | None] = ContextVar("jobpilot_task_id", default=None)


@contextmanager
def bind_task_usage(task_id: int | None) -> Iterator[None]:
    token = _current_task_id.set(task_id)
    try:
        yield
    finally:
        _current_task_id.reset(token)


def current_task_id() -> int | None:
    return _current_task_id.get()


def estimate_chat_cost(input_tokens: int, output_tokens: int) -> float:
    return (
        max(0, input_tokens) * settings.llm_input_cost_per_1m
        + max(0, output_tokens) * settings.llm_output_cost_per_1m
    ) / 1_000_000.0


def estimate_embedding_cost(input_tokens: int) -> float:
    return max(0, input_tokens) * settings.embedding_cost_per_1m / 1_000_000.0


def record_usage(
    *,
    component: str,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int | None = None,
    cost_usd: float = 0.0,
    duration_seconds: float = 0.0,
    metadata: dict[str, Any] | None = None,
    task_id: int | None = None,
) -> dict[str, Any]:
    return db.record_usage_event(
        task_id=current_task_id() if task_id is None else task_id,
        component=component,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=cost_usd,
        duration_seconds=duration_seconds,
        metadata=metadata,
    )
