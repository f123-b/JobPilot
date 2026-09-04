from __future__ import annotations

import json
from typing import Any

from .backend import all_rows, connect, insert_id, load_json, lock, now, one


def task_status_counts() -> dict[str, int]:
    with connect() as conn: rows = all_rows(conn, "SELECT status,COUNT(*) AS n FROM tasks GROUP BY status")
    return {str(x["status"]): int(x["n"]) for x in rows}


def record_usage_event(*, task_id: int | None, component: str, model: str | None = None, input_tokens: int = 0, output_tokens: int = 0, total_tokens: int | None = None, estimated_cost_usd: float = 0.0, duration_seconds: float = 0.0, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    total = int(total_tokens if total_tokens is not None else input_tokens + output_tokens)
    with lock, connect() as conn:
        event_id = insert_id(conn, "INSERT INTO usage_events(task_id,component,model,input_tokens,output_tokens,total_tokens,estimated_cost_usd,duration_seconds,metadata_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (task_id, component, model, int(input_tokens), int(output_tokens), total, float(estimated_cost_usd), float(duration_seconds), json.dumps(metadata or {}, ensure_ascii=False, default=str), now())); conn.commit(); row = one(conn, "SELECT * FROM usage_events WHERE id=?", (event_id,)) or {}
    row["metadata"] = load_json(row.pop("metadata_json", None)) or {}; return row


def list_usage_events(task_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with connect() as conn: rows = all_rows(conn, "SELECT * FROM usage_events WHERE task_id=? ORDER BY id DESC LIMIT ?", (task_id, limit)) if task_id is not None else all_rows(conn, "SELECT * FROM usage_events ORDER BY id DESC LIMIT ?", (limit,))
    for row in rows: row["metadata"] = load_json(row.pop("metadata_json", None)) or {}
    return rows


def usage_summary(task_id: int | None = None) -> dict[str, Any]:
    where = " WHERE task_id=?" if task_id is not None else ""; params = (task_id,) if task_id is not None else ()
    with connect() as conn: row = one(conn, f"SELECT COUNT(*) AS events,COALESCE(SUM(input_tokens),0) AS input_tokens,COALESCE(SUM(output_tokens),0) AS output_tokens,COALESCE(SUM(total_tokens),0) AS total_tokens,COALESCE(SUM(estimated_cost_usd),0) AS estimated_cost_usd,COALESCE(SUM(duration_seconds),0) AS duration_seconds FROM usage_events{where}", params) or {}
    return {"events": int(row.get("events") or 0), "input_tokens": int(row.get("input_tokens") or 0), "output_tokens": int(row.get("output_tokens") or 0), "total_tokens": int(row.get("total_tokens") or 0), "estimated_cost_usd": round(float(row.get("estimated_cost_usd") or 0), 6), "duration_seconds": round(float(row.get("duration_seconds") or 0), 3)}


def save_benchmark_run(name: str, version: str, score: float, passed: bool, detail: dict[str, Any]) -> dict[str, Any]:
    with lock, connect() as conn: run_id = insert_id(conn, "INSERT INTO benchmark_runs(name,version,score,passed,detail_json,created_at) VALUES (?,?,?,?,?,?)", (name, version, float(score), bool(passed), json.dumps(detail, ensure_ascii=False, default=str), now())); conn.commit(); row = one(conn, "SELECT * FROM benchmark_runs WHERE id=?", (run_id,)) or {}
    row["passed"] = bool(row.get("passed")); row["detail"] = load_json(row.pop("detail_json", None)) or {}; return row


def list_benchmark_runs(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as conn: rows = all_rows(conn, "SELECT * FROM benchmark_runs ORDER BY id DESC LIMIT ?", (limit,))
    for row in rows: row["passed"] = bool(row.get("passed")); row["detail"] = load_json(row.pop("detail_json", None)) or {}
    return rows


def failure_counts() -> dict[str, int]:
    with connect() as conn: rows = all_rows(conn, "SELECT COALESCE(failure_category,'none') AS category,COUNT(*) AS n FROM tasks GROUP BY COALESCE(failure_category,'none')")
    return {str(x["category"]): int(x["n"]) for x in rows}
