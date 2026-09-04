from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .backend import all_rows, connect, execute, executemany, insert_id, load_json, lock, now, one


def _normalize(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[?#].*$", "", value)
    return re.sub(r"\s+", " ", value)


def job_fingerprint(data: dict[str, Any]) -> str:
    stable = "|".join(_normalize(data.get(key)) for key in ("title", "company", "location", "url"))
    return hashlib.sha256(stable.encode()).hexdigest()[:24]


def save_job(data: dict[str, Any]) -> dict[str, Any]:
    fingerprint = data.get("fingerprint") or job_fingerprint(data); ts = now()
    with lock, connect() as conn:
        existing = one(conn, "SELECT id FROM jobs WHERE fingerprint=?", (fingerprint,))
        if existing:
            execute(conn, "UPDATE jobs SET title=?,company=?,location=?,url=?,jd_text=?,source=?,match_score=COALESCE(?,match_score),updated_at=? WHERE id=?", (data["title"], data.get("company"), data.get("location"), data.get("url"), data.get("jd_text", ""), data.get("source"), data.get("match_score"), ts, existing["id"])); conn.commit(); job_id = int(existing["id"])
        else:
            job_id = insert_id(conn, "INSERT INTO jobs(title,company,location,url,jd_text,source,fingerprint,match_score,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (data["title"], data.get("company"), data.get("location"), data.get("url"), data.get("jd_text", ""), data.get("source"), fingerprint, data.get("match_score"), ts, ts)); conn.commit()
    return get_job(job_id) or {}


def count_jobs() -> int:
    with connect() as conn: return int((one(conn, "SELECT COUNT(*) AS n FROM jobs") or {"n": 0})["n"])


def ingest_jobs(items: list[dict[str, Any]]) -> dict[str, Any]:
    before = count_jobs(); saved = [save_job(x) for x in items]; inserted = count_jobs() - before
    return {"received": len(items), "inserted": inserted, "deduplicated": len(items) - inserted, "jobs": saved}


def get_job(job_id: int) -> dict[str, Any] | None:
    with connect() as conn: return one(conn, "SELECT * FROM jobs WHERE id=?", (job_id,))


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as conn: return all_rows(conn, "SELECT * FROM jobs ORDER BY COALESCE(match_score,-1) DESC,id DESC LIMIT ?", (limit,))


def create_task(objective: str, task_type: str, payload: dict[str, Any], requires_approval: bool) -> dict[str, Any]:
    ts = now(); status = "waiting_approval" if requires_approval else "queued"
    with lock, connect() as conn:
        task_id = insert_id(conn, "INSERT INTO tasks(objective,task_type,status,requires_approval,approved,payload_json,retry_count,created_at,updated_at) VALUES (?,?,?,?,?,?,0,?,?)", (objective, task_type, status, bool(requires_approval), None, json.dumps(payload, ensure_ascii=False), ts, ts))
        thread_id = f"jobpilot-task-{task_id}"; execute(conn, "UPDATE tasks SET workflow_thread_id=? WHERE id=?", (thread_id, task_id)); conn.commit()
    add_trace(task_id, "task_created", {"status": status, "requires_approval": requires_approval, "thread_id": thread_id})
    return get_task(task_id) or {}


def _decode_task(row: dict[str, Any]) -> dict[str, Any]:
    row["payload"] = load_json(row.pop("payload_json")) or {}; row["requires_approval"] = bool(row["requires_approval"]); row["approved"] = None if row["approved"] is None else bool(row["approved"])
    row["evaluation"] = load_json(row.pop("evaluation_json", None)); row["plan"] = load_json(row.pop("plan_json", None)); row["workflow"] = load_json(row.pop("workflow_json", None)); return row


def get_task(task_id: int) -> dict[str, Any] | None:
    with connect() as conn: row = one(conn, "SELECT * FROM tasks WHERE id=?", (task_id,))
    return _decode_task(row) if row else None


def list_tasks(limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn: rows = all_rows(conn, "SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)) if status else all_rows(conn, "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
    return [_decode_task(x) for x in rows]


def update_task(task_id: int, **fields: Any) -> None:
    if not fields: return
    for source, target in (("evaluation", "evaluation_json"), ("plan", "plan_json"), ("workflow", "workflow_json")):
        if source in fields:
            value = fields.pop(source); fields[target] = json.dumps(value, ensure_ascii=False, default=str) if value is not None else None
    fields["updated_at"] = now(); keys = list(fields)
    with lock, connect() as conn: execute(conn, "UPDATE tasks SET " + ",".join(f"{k}=?" for k in keys) + " WHERE id=?", (*[fields[k] for k in keys], task_id)); conn.commit()


def approve_task(task_id: int, approved: bool, note: str | None = None) -> dict[str, Any] | None:
    update_task(task_id, approved=bool(approved), status="queued" if approved else "rejected"); add_trace(task_id, "approval", {"approved": approved, "note": note}); return get_task(task_id)


def add_trace(task_id: int, event_type: str, detail: dict[str, Any]) -> dict[str, Any]:
    with lock, connect() as conn: trace_id = insert_id(conn, "INSERT INTO traces(task_id,event_type,detail_json,created_at) VALUES (?,?,?,?)", (task_id, event_type, json.dumps(detail, ensure_ascii=False, default=str), now())); conn.commit()
    return get_trace(trace_id) or {}


def get_trace(trace_id: int) -> dict[str, Any] | None:
    with connect() as conn: row = one(conn, "SELECT * FROM traces WHERE id=?", (trace_id,))
    if row: row["detail"] = load_json(row.pop("detail_json")) or {}
    return row


def list_traces(task_id: int, after_id: int = 0) -> list[dict[str, Any]]:
    with connect() as conn: rows = all_rows(conn, "SELECT * FROM traces WHERE task_id=? AND id>? ORDER BY id", (task_id, after_id))
    for row in rows: row["detail"] = load_json(row.pop("detail_json")) or {}
    return rows


def replace_resume_chunks(user_id: str, source_id: str, items: list[dict[str, Any]]) -> None:
    ts = now(); params = [(user_id, source_id, int(x["chunk_index"]), x.get("section") or "resume", x.get("content") or "", json.dumps(x.get("embedding") or []), x.get("embedding_backend") or "unknown", json.dumps(x.get("metadata") or {}, ensure_ascii=False), ts) for x in items]
    with lock, connect() as conn:
        execute(conn, "DELETE FROM resume_chunks WHERE user_id=? AND source_id=?", (user_id, source_id))
        if params: executemany(conn, "INSERT INTO resume_chunks(user_id,source_id,chunk_index,section,content,embedding_json,embedding_backend,metadata_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)", params)
        conn.commit()


def list_resume_chunks(user_id: str, source_id: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn: rows = all_rows(conn, "SELECT * FROM resume_chunks WHERE user_id=? AND source_id=? ORDER BY chunk_index", (user_id, source_id)) if source_id else all_rows(conn, "SELECT * FROM resume_chunks WHERE user_id=? ORDER BY id DESC", (user_id,))
    for row in rows: row["embedding"] = load_json(row.pop("embedding_json", None)) or []; row["metadata"] = load_json(row.pop("metadata_json", None)) or {}
    return rows


def upsert_user_memory(user_id: str, key: str, value: Any) -> dict[str, Any]:
    payload = json.dumps(value, ensure_ascii=False, default=str); ts = now()
    with lock, connect() as conn:
        execute(conn, "INSERT INTO user_memory(user_id,key,value_json,updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at", (user_id, key, payload, ts)); conn.commit(); row = one(conn, "SELECT * FROM user_memory WHERE user_id=? AND key=?", (user_id, key)) or {}
    row["value"] = load_json(row.pop("value_json", None)); return row


def list_user_memory(user_id: str) -> list[dict[str, Any]]:
    with connect() as conn: rows = all_rows(conn, "SELECT * FROM user_memory WHERE user_id=? ORDER BY key", (user_id,))
    for row in rows: row["value"] = load_json(row.pop("value_json", None))
    return rows


def upsert_job_memory(user_id: str, job_fingerprint: str, status: str, note: str | None = None) -> dict[str, Any]:
    with lock, connect() as conn:
        execute(conn, "INSERT INTO job_memory(user_id,job_fingerprint,status,note,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(user_id,job_fingerprint) DO UPDATE SET status=excluded.status,note=excluded.note,updated_at=excluded.updated_at", (user_id, job_fingerprint, status, note, now())); conn.commit(); return one(conn, "SELECT * FROM job_memory WHERE user_id=? AND job_fingerprint=?", (user_id, job_fingerprint)) or {}


def get_job_memory(user_id: str, job_fingerprint: str) -> dict[str, Any] | None:
    with connect() as conn: return one(conn, "SELECT * FROM job_memory WHERE user_id=? AND job_fingerprint=?", (user_id, job_fingerprint))


def list_job_memory(user_id: str) -> list[dict[str, Any]]:
    with connect() as conn: return all_rows(conn, "SELECT * FROM job_memory WHERE user_id=? ORDER BY updated_at DESC", (user_id,))
