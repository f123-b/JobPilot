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
                plan_json TEXT,
                workflow_json TEXT,
                current_agent TEXT,
                workflow_thread_id TEXT,
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

            CREATE TABLE IF NOT EXISTS resume_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                section TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                embedding_backend TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, key)
            );

            CREATE TABLE IF NOT EXISTS job_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                job_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, job_fingerprint)
            );
            """
        )
        # Backward-compatible migrations from V0.1 / V0.2 databases.
        _ensure_column(conn, "jobs", "location", "TEXT")
        _ensure_column(conn, "jobs", "source", "TEXT")
        _ensure_column(conn, "jobs", "fingerprint", "TEXT")
        _ensure_column(conn, "jobs", "updated_at", "TEXT")
        _ensure_column(conn, "tasks", "retry_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "tasks", "evaluation_json", "TEXT")
        _ensure_column(conn, "tasks", "plan_json", "TEXT")
        _ensure_column(conn, "tasks", "workflow_json", "TEXT")
        _ensure_column(conn, "tasks", "current_agent", "TEXT")
        _ensure_column(conn, "tasks", "workflow_thread_id", "TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint) WHERE fingerprint IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_task_id ON traces(task_id, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_resume_chunks_user ON resume_chunks(user_id, source_id, chunk_index)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_memory_user ON job_memory(user_id, status)")
        conn.commit()


def _normalize(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[?#].*$", "", value)
    return re.sub(r"\s+", " ", value)


def job_fingerprint(data: dict[str, Any]) -> str:
    stable = "|".join(
        [
            _normalize(data.get("title")),
            _normalize(data.get("company")),
            _normalize(data.get("location")),
            _normalize(data.get("url")),
        ]
    )
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
                (
                    data["title"], data.get("company"), data.get("location"), data.get("url"),
                    data.get("jd_text", ""), data.get("source"), data.get("match_score"), now, existing["id"],
                ),
            )
            conn.commit()
            return get_job(existing["id"])  # type: ignore[return-value]

        cur = conn.execute(
            """INSERT INTO jobs(title, company, location, url, jd_text, source, fingerprint,
               match_score, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["title"], data.get("company"), data.get("location"), data.get("url"),
                data.get("jd_text", ""), data.get("source"), fingerprint, data.get("match_score"), now, now,
            ),
        )
        conn.commit()
        return get_job(cur.lastrowid)  # type: ignore[return-value]


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
        rows = conn.execute("SELECT * FROM jobs ORDER BY COALESCE(match_score, -1) DESC, id DESC LIMIT ?", (limit,)).fetchall()
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
        task_id = cur.lastrowid
        thread_id = f"jobpilot-task-{task_id}"
        conn.execute("UPDATE tasks SET workflow_thread_id=? WHERE id=?", (thread_id, task_id))
        conn.commit()
    add_trace(task_id, "task_created", {"status": status, "requires_approval": requires_approval, "thread_id": thread_id})
    return get_task(task_id)  # type: ignore[return-value]


def _load_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def get_task(task_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = _load_json(d.pop("payload_json")) or {}
        d["requires_approval"] = bool(d["requires_approval"])
        d["approved"] = None if d["approved"] is None else bool(d["approved"])
        d["evaluation"] = _load_json(d.pop("evaluation_json", None))
        d["plan"] = _load_json(d.pop("plan_json", None))
        d["workflow"] = _load_json(d.pop("workflow_json", None))
        return d


def update_task(task_id: int, **fields: Any) -> None:
    if not fields:
        return
    for source, target in (("evaluation", "evaluation_json"), ("plan", "plan_json"), ("workflow", "workflow_json")):
        if source in fields:
            value = fields.pop(source)
            fields[target] = json.dumps(value, ensure_ascii=False, default=str) if value is not None else None
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
        cur = conn.execute(
            "INSERT INTO traces(task_id, event_type, detail_json, created_at) VALUES (?, ?, ?, ?)",
            (task_id, event_type, json.dumps(detail, ensure_ascii=False, default=str), _now()),
        )
        conn.commit()
        trace_id = cur.lastrowid
    return get_trace(trace_id)  # type: ignore[return-value]


def get_trace(trace_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM traces WHERE id=?", (trace_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["detail"] = _load_json(d.pop("detail_json")) or {}
        return d


def list_traces(task_id: int, after_id: int = 0) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM traces WHERE task_id=? AND id>? ORDER BY id", (task_id, after_id)
        ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["detail"] = _load_json(d.pop("detail_json")) or {}
            out.append(d)
        return out


def replace_resume_chunks(user_id: str, source_id: str, items: list[dict[str, Any]]) -> None:
    now = _now()
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM resume_chunks WHERE user_id=? AND source_id=?", (user_id, source_id))
        conn.executemany(
            """INSERT INTO resume_chunks(user_id,source_id,chunk_index,section,content,
               embedding_json,embedding_backend,metadata_json,created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    user_id,
                    source_id,
                    int(item["chunk_index"]),
                    item.get("section") or "resume",
                    item.get("content") or "",
                    json.dumps(item.get("embedding") or []),
                    item.get("embedding_backend") or "unknown",
                    json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                    now,
                )
                for item in items
            ],
        )
        conn.commit()


def list_resume_chunks(user_id: str, source_id: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if source_id:
            rows = conn.execute(
                "SELECT * FROM resume_chunks WHERE user_id=? AND source_id=? ORDER BY chunk_index",
                (user_id, source_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM resume_chunks WHERE user_id=? ORDER BY id DESC", (user_id,)
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d["embedding"] = _load_json(d.pop("embedding_json", None)) or []
            d["metadata"] = _load_json(d.pop("metadata_json", None)) or {}
            out.append(d)
        return out


def upsert_user_memory(user_id: str, key: str, value: Any) -> dict[str, Any]:
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO user_memory(user_id,key,value_json,updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id,key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
            (user_id, key, json.dumps(value, ensure_ascii=False, default=str), now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM user_memory WHERE user_id=? AND key=?", (user_id, key)).fetchone()
    d = dict(row)
    d["value"] = _load_json(d.pop("value_json"))
    return d


def list_user_memory(user_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM user_memory WHERE user_id=? ORDER BY key", (user_id,)).fetchall()
    out=[]
    for row in rows:
        d=dict(row); d["value"]=_load_json(d.pop("value_json")); out.append(d)
    return out


def upsert_job_memory(user_id: str, job_fingerprint: str, status: str, note: str | None = None) -> dict[str, Any]:
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO job_memory(user_id,job_fingerprint,status,note,updated_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id,job_fingerprint) DO UPDATE SET status=excluded.status,note=excluded.note,updated_at=excluded.updated_at""",
            (user_id, job_fingerprint, status, note, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM job_memory WHERE user_id=? AND job_fingerprint=?", (user_id, job_fingerprint)
        ).fetchone()
    return dict(row)


def get_job_memory(user_id: str, job_fingerprint: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM job_memory WHERE user_id=? AND job_fingerprint=?", (user_id, job_fingerprint)
        ).fetchone()
        return dict(row) if row else None


def list_job_memory(user_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM job_memory WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]
