from __future__ import annotations

from typing import Any, Literal

from .. import db

JobMemoryStatus = Literal["seen", "saved", "applied", "rejected", "interview", "offer"]


def set_user_preference(user_id: str, key: str, value: Any) -> dict[str, Any]:
    return db.upsert_user_memory(user_id=user_id, key=key, value=value)


def get_user_preferences(user_id: str) -> dict[str, Any]:
    return {item["key"]: item["value"] for item in db.list_user_memory(user_id)}


def remember_job(user_id: str, job: dict[str, Any], status: JobMemoryStatus, note: str | None = None) -> dict[str, Any]:
    fingerprint = job.get("fingerprint") or db.job_fingerprint(job)
    return db.upsert_job_memory(user_id=user_id, job_fingerprint=fingerprint, status=status, note=note)


def remember_seen_if_new(user_id: str, job: dict[str, Any]) -> dict[str, Any]:
    fingerprint = job.get("fingerprint") or db.job_fingerprint(job)
    existing = db.get_job_memory(user_id=user_id, job_fingerprint=fingerprint)
    if existing:
        return existing
    return db.upsert_job_memory(user_id=user_id, job_fingerprint=fingerprint, status="seen", note=None)


def get_job_memory(user_id: str, fingerprint: str) -> dict[str, Any] | None:
    return db.get_job_memory(user_id=user_id, job_fingerprint=fingerprint)
