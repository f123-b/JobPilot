from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from ..config import settings

lock = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def backend_name() -> str:
    return "postgres" if settings.app_database_url else "sqlite"


def sql(text: str) -> str:
    return text.replace("?", "%s") if backend_name() == "postgres" else text


@contextmanager
def connect() -> Iterator[Any]:
    if backend_name() == "postgres":
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PostgreSQL application DB requires psycopg[binary,pool]") from exc
        conn = psycopg.connect(settings.app_database_url, row_factory=dict_row)
    else:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(settings.database_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def execute(conn: Any, statement: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(sql(statement), params)


def executemany(conn: Any, statement: str, params: list[tuple[Any, ...]]) -> Any:
    return conn.executemany(sql(statement), params)


def one(conn: Any, statement: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    row = execute(conn, statement, params).fetchone()
    return dict(row) if row is not None else None


def all_rows(conn: Any, statement: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in execute(conn, statement, params).fetchall()]


def insert_id(conn: Any, statement: str, params: tuple[Any, ...]) -> int:
    if backend_name() == "postgres":
        row = conn.execute(sql(statement.rstrip().rstrip(";") + " RETURNING id"), params).fetchone()
        return int(row["id"])
    return int(conn.execute(statement, params).lastrowid)


def load_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _columns(conn: Any, table: str) -> set[str]:
    if backend_name() == "postgres":
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
            (table,),
        ).fetchall()
        return {str(row["column_name"]) for row in rows}
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: Any, table: str, name: str, ddl: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,company TEXT,location TEXT,url TEXT,jd_text TEXT NOT NULL,source TEXT,fingerprint TEXT,match_score INTEGER,created_at TEXT NOT NULL,updated_at TEXT);
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,objective TEXT NOT NULL,task_type TEXT NOT NULL,status TEXT NOT NULL,requires_approval INTEGER NOT NULL DEFAULT 0,approved INTEGER,payload_json TEXT NOT NULL,result_text TEXT,error_text TEXT,retry_count INTEGER NOT NULL DEFAULT 0,evaluation_json TEXT,plan_json TEXT,workflow_json TEXT,current_agent TEXT,workflow_thread_id TEXT,failure_category TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS traces (id INTEGER PRIMARY KEY AUTOINCREMENT,task_id INTEGER NOT NULL,event_type TEXT NOT NULL,detail_json TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(task_id) REFERENCES tasks(id));
CREATE TABLE IF NOT EXISTS resume_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,source_id TEXT NOT NULL,chunk_index INTEGER NOT NULL,section TEXT NOT NULL,content TEXT NOT NULL,embedding_json TEXT NOT NULL,embedding_backend TEXT NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_memory (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,key TEXT NOT NULL,value_json TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(user_id,key));
CREATE TABLE IF NOT EXISTS job_memory (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,job_fingerprint TEXT NOT NULL,status TEXT NOT NULL,note TEXT,updated_at TEXT NOT NULL,UNIQUE(user_id,job_fingerprint));
CREATE TABLE IF NOT EXISTS task_queue (id INTEGER PRIMARY KEY AUTOINCREMENT,task_id INTEGER NOT NULL UNIQUE,status TEXT NOT NULL,worker_id TEXT,available_at TEXT NOT NULL,lease_until TEXT,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(task_id) REFERENCES tasks(id));
CREATE TABLE IF NOT EXISTS usage_events (id INTEGER PRIMARY KEY AUTOINCREMENT,task_id INTEGER,component TEXT NOT NULL,model TEXT,input_tokens INTEGER NOT NULL DEFAULT 0,output_tokens INTEGER NOT NULL DEFAULT 0,total_tokens INTEGER NOT NULL DEFAULT 0,estimated_cost_usd REAL NOT NULL DEFAULT 0,duration_seconds REAL NOT NULL DEFAULT 0,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS benchmark_runs (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,version TEXT NOT NULL,score REAL NOT NULL,passed INTEGER NOT NULL,detail_json TEXT NOT NULL,created_at TEXT NOT NULL);
"""

POSTGRES_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS jobs (id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,company TEXT,location TEXT,url TEXT,jd_text TEXT NOT NULL,source TEXT,fingerprint TEXT,match_score INTEGER,created_at TEXT NOT NULL,updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS tasks (id BIGSERIAL PRIMARY KEY,objective TEXT NOT NULL,task_type TEXT NOT NULL,status TEXT NOT NULL,requires_approval BOOLEAN NOT NULL DEFAULT FALSE,approved BOOLEAN,payload_json TEXT NOT NULL,result_text TEXT,error_text TEXT,retry_count INTEGER NOT NULL DEFAULT 0,evaluation_json TEXT,plan_json TEXT,workflow_json TEXT,current_agent TEXT,workflow_thread_id TEXT,failure_category TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS traces (id BIGSERIAL PRIMARY KEY,task_id BIGINT NOT NULL REFERENCES tasks(id),event_type TEXT NOT NULL,detail_json TEXT NOT NULL,created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS resume_chunks (id BIGSERIAL PRIMARY KEY,user_id TEXT NOT NULL,source_id TEXT NOT NULL,chunk_index INTEGER NOT NULL,section TEXT NOT NULL,content TEXT NOT NULL,embedding_json TEXT NOT NULL,embedding_backend TEXT NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS user_memory (id BIGSERIAL PRIMARY KEY,user_id TEXT NOT NULL,key TEXT NOT NULL,value_json TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(user_id,key))",
    "CREATE TABLE IF NOT EXISTS job_memory (id BIGSERIAL PRIMARY KEY,user_id TEXT NOT NULL,job_fingerprint TEXT NOT NULL,status TEXT NOT NULL,note TEXT,updated_at TEXT NOT NULL,UNIQUE(user_id,job_fingerprint))",
    "CREATE TABLE IF NOT EXISTS task_queue (id BIGSERIAL PRIMARY KEY,task_id BIGINT NOT NULL UNIQUE REFERENCES tasks(id),status TEXT NOT NULL,worker_id TEXT,available_at TEXT NOT NULL,lease_until TEXT,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS usage_events (id BIGSERIAL PRIMARY KEY,task_id BIGINT,component TEXT NOT NULL,model TEXT,input_tokens INTEGER NOT NULL DEFAULT 0,output_tokens INTEGER NOT NULL DEFAULT 0,total_tokens INTEGER NOT NULL DEFAULT 0,estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS benchmark_runs (id BIGSERIAL PRIMARY KEY,name TEXT NOT NULL,version TEXT NOT NULL,score DOUBLE PRECISION NOT NULL,passed BOOLEAN NOT NULL,detail_json TEXT NOT NULL,created_at TEXT NOT NULL)",
]


def init_db() -> None:
    with lock, connect() as conn:
        if backend_name() == "postgres":
            for statement in POSTGRES_SCHEMA:
                conn.execute(statement)
        else:
            conn.executescript(SQLITE_SCHEMA)
        for table, name, ddl in [
            ("jobs", "location", "TEXT"), ("jobs", "source", "TEXT"), ("jobs", "fingerprint", "TEXT"), ("jobs", "updated_at", "TEXT"),
            ("tasks", "retry_count", "INTEGER NOT NULL DEFAULT 0"), ("tasks", "evaluation_json", "TEXT"), ("tasks", "plan_json", "TEXT"),
            ("tasks", "workflow_json", "TEXT"), ("tasks", "current_agent", "TEXT"), ("tasks", "workflow_thread_id", "TEXT"), ("tasks", "failure_category", "TEXT"),
        ]:
            _ensure_column(conn, table, name, ddl)
        for statement in [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint) WHERE fingerprint IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_traces_task_id ON traces(task_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, id)",
            "CREATE INDEX IF NOT EXISTS idx_resume_chunks_user ON resume_chunks(user_id, source_id, chunk_index)",
            "CREATE INDEX IF NOT EXISTS idx_job_memory_user ON job_memory(user_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_queue_claim ON task_queue(status, available_at, id)",
            "CREATE INDEX IF NOT EXISTS idx_usage_task ON usage_events(task_id, id)",
        ]:
            conn.execute(statement)
        conn.commit()
