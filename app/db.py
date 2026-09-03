from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from .config import settings

_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT,
                location TEXT,
                url TEXT,
                jd_text TEXT NOT NULL,
                source TEXT,
                fingerprint TEXT,
                match_score INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                objective TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                requires_approval INTEGER NOT NULL DEFAULT 0,
                approved INTEGER,
                payload_json TEXT NOT NULL,
                result_text TEXT,
                error_text TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                evaluation_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            """
        )
        _ensure_column(conn, "jobs", "location", "TEXT")
        _ensure_column(conn, "jobs", "source", "TEXT")
        _ensure_column(conn, "jobs", "fingerprint", "TEXT")
        _ensure_column(conn, "jobs", "updated_at", "TEXT")
        _ensure_column(conn, "tasks", "retry_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "tasks", "evaluation_json", "TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint) WHERE fingerprint IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_task_id ON traces(task_id, id)")
        conn.commit()


def _normalize(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[?#].*$", "", value)
    return re.sub(r"\s+", " ", value)


def job_fingerprint(data: dict[str, Any]) -> str:
    stable = "|".join([_normalize(data.get("title")), _normalize(data.get("company")), _normalize(data.get("location")), _normalize(data.get("url"))])
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def save_job(data: dict[str, Any]) -> dict[str, Any]:
    fingerprint = data.get("fingerprint") or job_fingerprint(data)
    now = _now()
    with _lock, _connect() as conn:
        existing = conn.execute("SELECT id FROM jobs WHERE fingerprint=?", (fingerprint,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE jobs SET title=?, company=?, location=?, url=?, jd_text=?, source=?,
                   match_score=COALESCE(?, match_score), updated_at=? WHERE id=?""",
                (data["title"], data.get("company"), data.get("location"), data.get("url"), data.get("jd_text", ""), data.get("source"), data.get("match_score"), now, existing["id"]),
            )
            conn.commit()
            return get_job(existing["id"])
        cur = conn.execute(
            """INSERT INTO jobs(title, company, location, url, jd_text, source, fingerprint,
               match_score, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data["title"], data.get("company"), data.get("location"), data.get("url"), data.get("jd_text", ""), data.get("source"), fingerprint, data.get("match_score"), now, now),
        )
        conn.commit()
        return get_job(cur.lastrowid)


def ingest_jobs(items: list[dict[str, Any]]) -> dict[str, Any]:
    before = count_jobs()
    saved = [save_job(item) for item in items]
    after = count_jobs()
    return {"received": len(items), "inserted": after - before, "deduplicated": len(items) - (after - before), "jobs": saved}


def count_jobs() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])


def get_job(job_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def create_task(objective: str, task_type: str, payload: dict[str, Any], requires_approval: bool) -> dict[str, Any]:
    now = _now()
    status = "waiting_approval" if requires_approval else "queued"
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO tasks(objective, task_type, status, requires_approval, approved, payload_json,
               retry_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (objective, task_type, status, int(requires_approval), None, json.dumps(payload, ensure_ascii=False), now, now),
        )
        conn.commit()
        task_id = cur.lastrowid
    add_trace(task_id, "task_created", {"status": status, "requires_approval": requires_approval})
    return get_task(task_id)


def get_task(task_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        d["requires_approval"] = bool(d["requires_approval"])
        d["approved"] = None if d["approved"] is None else bool(d["approved"])
        d["evaluation"] = json.loads(d.pop("evaluation_json")) if d.get("evaluation_json") else None
        return d


def update_task(task_id: int, **fields: Any) -> None:
    if not fields:
        return
    if "evaluation" in fields:
        fields["evaluation_json"] = json.dumps(fields.pop("evaluation"), ensure_ascii=False)
    fields["updated_at"] = _now()
    keys = list(fields)
    values = [fields[k] for k in keys]
    sql = "UPDATE tasks SET " + ", ".join(f"{k}=?" for k in keys) + " WHERE id=?"
    with _lock, _connect() as conn:
        conn.execute(sql, (*values, task_id))
        conn.commit()


def approve_task(task_id: int, approved: bool, note: str | None = None) -> dict[str, Any] | None:
    status = "queued" if approved else "rejected"
    update_task(task_id, approved=int(approved), status=status)
    add_trace(task_id, "approval", {"approved": approved, "note": note})
    return get_task(task_id)


def add_trace(task_id: int, event_type: str, detail: dict[str, Any]) -> dict[str, Any]:
    with _lock, _connect() as conn:
        cur = conn.execute("INSERT INTO traces(task_id, event_type, detail_json, created_at) VALUES (?, ?, ?, ?)", (task_id, event_type, json.dumps(detail, ensure_ascii=False, default=str), _now()))
        conn.commit()
        trace_id = cur.lastrowid
    return get_trace(trace_id)


def get_trace(trace_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE id=?", (trace_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["detail"] = json.loads(d.pop("detail_json"))
        return d


def list_traces(task_id: int, after_id: int = 0) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM traces WHERE task_id=? AND id>? ORDER BY id", (task_id, after_id)).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["detail"] = json.loads(d.pop("detail_json"))
            out.append(d)
        return out
