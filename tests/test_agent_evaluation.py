from app.schemas import BrowserRunResult
from app.services.agent_evaluation import evaluate_run
from app.services.replanner import replan_objective


def test_successful_run_passes_quality_gate():
    run = BrowserRunResult(success=True, final_result="Found 5 jobs", actions=["search", "click", "extract"], errors=[], step_count=3, duration_seconds=4.2)
    result = evaluate_run(run)
    assert result.passed is True
    assert result.score >= 65


def test_transient_failure_is_retryable_and_replanned():
    run = BrowserRunResult(success=False, errors=["navigation timeout"], step_count=2)
    result = evaluate_run(run)
    assert result.retryable is True
    revised = replan_objective("Find jobs", run, 2)
    assert "navigation timeout" in revised
    assert "Retry attempt 2" in revised
