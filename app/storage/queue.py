from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .backend import backend_name, connect, execute, lock, now, one, all_rows
from .core import add_trace


def enqueue_task(task_id: int, *, delay_seconds: float = 0.0) -> dict[str, Any]:
    current = datetime.now(timezone.utc); available = (current + timedelta(seconds=max(0.0, delay_seconds))).isoformat(); ts = current.isoformat()
    with lock, connect() as conn:
        execute(conn, "INSERT INTO task_queue(task_id,status,worker_id,available_at,lease_until,attempts,last_error,created_at,updated_at) VALUES (?,'queued',NULL,?,NULL,0,NULL,?,?) ON CONFLICT(task_id) DO UPDATE SET status='queued',worker_id=NULL,available_at=excluded.available_at,lease_until=NULL,last_error=NULL,updated_at=excluded.updated_at", (task_id, available, ts, ts)); conn.commit()
    add_trace(task_id, "queue_enqueued", {"available_at": available}); return get_queue_item(task_id) or {}


def get_queue_item(task_id: int) -> dict[str, Any] | None:
    with connect() as conn: return one(conn, "SELECT * FROM task_queue WHERE task_id=?", (task_id,))


def claim_next_task(worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    current = datetime.now(timezone.utc); ts = current.isoformat(); lease = (current + timedelta(seconds=max(10, lease_seconds))).isoformat()
    with lock, connect() as conn:
        if backend_name() == "postgres":  # pragma: no cover
            row = conn.execute("SELECT * FROM task_queue WHERE (status='queued' AND available_at<=%s) OR (status='running' AND lease_until IS NOT NULL AND lease_until<%s) ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1", (ts, ts)).fetchone()
            if not row: conn.rollback(); return None
            row = dict(row); conn.execute("UPDATE task_queue SET status='running',worker_id=%s,lease_until=%s,attempts=attempts+1,updated_at=%s WHERE id=%s", (worker_id, lease, ts, row["id"])); conn.commit(); return get_queue_item(int(row["task_id"]))
        conn.execute("BEGIN IMMEDIATE"); row = conn.execute("SELECT * FROM task_queue WHERE (status='queued' AND available_at<=?) OR (status='running' AND lease_until IS NOT NULL AND lease_until<?) ORDER BY id LIMIT 1", (ts, ts)).fetchone()
        if not row: conn.commit(); return None
        row = dict(row); conn.execute("UPDATE task_queue SET status='running',worker_id=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE id=?", (worker_id, lease, ts, row["id"])); conn.commit(); return get_queue_item(int(row["task_id"]))


def complete_queue_item(task_id: int) -> None:
    with lock, connect() as conn: execute(conn, "UPDATE task_queue SET status='done',worker_id=NULL,lease_until=NULL,updated_at=? WHERE task_id=?", (now(), task_id)); conn.commit()


def fail_queue_item(task_id: int, error: str, *, retry: bool, delay_seconds: float = 2.0) -> None:
    current = datetime.now(timezone.utc); available = (current + timedelta(seconds=max(0.0, delay_seconds))).isoformat()
    with lock, connect() as conn: execute(conn, "UPDATE task_queue SET status=?,worker_id=NULL,lease_until=NULL,available_at=?,last_error=?,updated_at=? WHERE task_id=?", ("queued" if retry else "dead", available, error[:4000], current.isoformat(), task_id)); conn.commit()


def queue_stats() -> dict[str, int]:
    with connect() as conn: rows = all_rows(conn, "SELECT status,COUNT(*) AS n FROM task_queue GROUP BY status")
    return {str(x["status"]): int(x["n"]) for x in rows}


def new_worker_id() -> str:
    return f"worker-{uuid.uuid4().hex[:10]}"
