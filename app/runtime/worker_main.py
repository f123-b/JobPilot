from __future__ import annotations

import asyncio

from .. import db
from .task_worker import TaskWorker


async def main() -> None:
    db.init_db()
    worker = TaskWorker()
    print(f"JobPilot worker started: {worker.worker_id}", flush=True)
    try:
        await worker.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
