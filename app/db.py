"""Compatibility facade for JobPilot application persistence.

V0.4 splits storage by concern while keeping the original `app.db` API stable.
"""
from .config import settings
from .storage.backend import backend_name, init_db
from .storage.core import (
    add_trace, approve_task, count_jobs, create_task, get_job, get_job_memory, get_task,
    get_trace, ingest_jobs, job_fingerprint, list_job_memory, list_jobs, list_resume_chunks,
    list_tasks, list_traces, list_user_memory, replace_resume_chunks, save_job, update_task,
    upsert_job_memory, upsert_user_memory,
)
from .storage.ops import (
    failure_counts, list_benchmark_runs, list_usage_events, record_usage_event,
    save_benchmark_run, task_status_counts, usage_summary,
)
from .storage.queue import (
    claim_next_task, complete_queue_item, enqueue_task, fail_queue_item, get_queue_item,
    new_worker_id, queue_stats,
)

__all__ = [name for name in globals() if not name.startswith("_")]
