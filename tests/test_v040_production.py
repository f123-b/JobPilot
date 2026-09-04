import asyncio

from app import db
from app.config import settings
from app.evaluation.benchmark import run_core_benchmark
from app.runtime import task_worker as worker_module
from app.runtime.task_worker import TaskWorker
from app.services.failure_classifier import classify_failure
from app.services.usage import bind_task_usage, record_usage


def _swap_db(tmp_path):
    original = {
        "database_path": settings.database_path,
        "database_backend": settings.database_backend,
        "database_url": settings.database_url,
        "postgres_url": settings.postgres_url,
    }
    object.__setattr__(settings, "database_path", tmp_path / "v040.db")
    object.__setattr__(settings, "database_backend", "sqlite")
    object.__setattr__(settings, "database_url", None)
    object.__setattr__(settings, "postgres_url", None)
    return original


def _restore(original):
    for key, value in original.items():
        object.__setattr__(settings, key, value)


def test_failure_taxonomy():
    assert classify_failure("navigation timeout").category == "timeout"
    assert classify_failure("429 too many requests").retryable is True
    assert classify_failure("reCAPTCHA challenge").category == "captcha"
    assert classify_failure("reCAPTCHA challenge").retryable is False


def test_usage_accounting_is_task_scoped(tmp_path):
    original = _swap_db(tmp_path)
    try:
        db.init_db()
        task = db.create_task("research a job page safely", "research", {"auto_execute": True}, False)
        with bind_task_usage(task["id"]):
            record_usage(component="llm.chat_json", model="demo", input_tokens=100, output_tokens=25, total_tokens=125, cost_usd=0.01)
            record_usage(component="embedding", model="embed-demo", input_tokens=50, total_tokens=50, cost_usd=0.002)
        summary = db.usage_summary(task["id"])
        assert summary["events"] == 2
        assert summary["total_tokens"] == 175
        assert summary["estimated_cost_usd"] == 0.012
    finally:
        _restore(original)


def test_durable_queue_claim_and_worker_completion(tmp_path):
    original = _swap_db(tmp_path)
    try:
        db.init_db()
        task = db.create_task("research a job page safely", "research", {"auto_execute": True}, False)
        db.enqueue_task(task["id"])

        async def fake_workflow(task_id: int):
            db.update_task(task_id, status="completed", result_text="ok")

        original_exec = worker_module.execute_multi_agent_workflow
        worker_module.execute_multi_agent_workflow = fake_workflow
        try:
            worker = TaskWorker("test-worker")
            assert asyncio.run(worker.run_once()) is True
        finally:
            worker_module.execute_multi_agent_workflow = original_exec

        assert db.get_task(task["id"])["status"] == "completed"
        assert db.get_queue_item(task["id"])["status"] == "done"
        assert db.queue_stats()["done"] == 1
    finally:
        _restore(original)


def test_core_benchmark_persists_result(tmp_path):
    original = _swap_db(tmp_path)
    try:
        db.init_db()
        result = asyncio.run(run_core_benchmark(persist=True))
        assert result["score"] == 100.0
        assert result["passed"] is True
        rows = db.list_benchmark_runs()
        assert rows and rows[0]["version"].startswith("v0.4")
    finally:
        _restore(original)
