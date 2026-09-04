from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass

from .. import db
from ..config import settings
from ..services.failure_classifier import classify_failure
from ..services.usage import bind_task_usage
from ..observability.telemetry import span
from ..workflow.multi_agent_graph import execute_multi_agent_workflow


@dataclass
class WorkerSnapshot:
    worker_id: str
    running: bool
    processed: int
    failed: int
    last_task_id: int | None


class TaskWorker:
    def __init__(self, worker_id: str | None = None) -> None:
        host = socket.gethostname().split(".")[0][:20]
        self.worker_id = worker_id or f"{host}-{db.new_worker_id()}"
        self._stopping = asyncio.Event()
        self.processed = 0
        self.failed = 0
        self.last_task_id: int | None = None
        self.running = False

    def snapshot(self) -> dict[str, object]:
        return WorkerSnapshot(
            worker_id=self.worker_id,
            running=self.running,
            processed=self.processed,
            failed=self.failed,
            last_task_id=self.last_task_id,
        ).__dict__

    async def run_once(self) -> bool:
        item = db.claim_next_task(self.worker_id, settings.worker_lease_seconds)
        if not item:
            return False
        task_id = int(item["task_id"])
        self.last_task_id = task_id
        db.add_trace(task_id, "worker_claimed", {"worker_id": self.worker_id, "queue_attempt": item.get("attempts")})
        try:
            with bind_task_usage(task_id), span("jobpilot.worker.execute", task_id=task_id, worker_id=self.worker_id):
                await execute_multi_agent_workflow(task_id)
            task = db.get_task(task_id) or {}
            if task.get("status") == "failed":
                metrics = ((task.get("evaluation") or {}).get("metrics") or {})
                category = metrics.get("failure_category")
                if category:
                    db.update_task(task_id, failure_category=category)
            if task.get("status") in {"completed", "failed", "rejected"}:
                db.complete_queue_item(task_id)
            else:
                raise RuntimeError(f"workflow returned non-terminal status={task.get('status')}")
            self.processed += 1
            return True
        except Exception as exc:
            self.failed += 1
            info = classify_failure(str(exc))
            retry = bool(info.retryable and int(item.get("attempts") or 0) < settings.worker_max_attempts)
            db.fail_queue_item(task_id, str(exc), retry=retry, delay_seconds=min(30.0, 2 ** int(item.get("attempts") or 1)))
            db.update_task(task_id, failure_category=info.category)
            db.add_trace(task_id, "worker_error", {**info.model_dump(), "error": str(exc), "retry": retry})
            return True

    async def run(self) -> None:
        self.running = True
        self._stopping.clear()
        try:
            while not self._stopping.is_set():
                worked = await self.run_once()
                if not worked:
                    try:
                        await asyncio.wait_for(self._stopping.wait(), timeout=settings.worker_poll_seconds)
                    except asyncio.TimeoutError:
                        pass
        finally:
            self.running = False

    def stop(self) -> None:
        self._stopping.set()
