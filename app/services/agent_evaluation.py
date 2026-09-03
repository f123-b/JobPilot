from __future__ import annotations

from ..config import settings
from ..schemas import AgentEvaluation, BrowserRunResult

_TRANSIENT_HINTS = ("timeout", "timed out", "temporary", "navigation", "network", "connection", "element", "not found", "stale", "rate limit", "429", "503", "502")


def evaluate_run(run: BrowserRunResult) -> AgentEvaluation:
    errors = [str(e) for e in run.errors if e]
    score = 0
    reasons: list[str] = []
    if run.success is True:
        score += 45
    elif run.success is None:
        score += 20
        reasons.append("Agent 未返回明确 success 标记")
    else:
        reasons.append("Agent 标记任务失败")
    if run.final_result.strip():
        score += 25
    else:
        reasons.append("缺少最终结果")
    if run.actions:
        score += min(15, max(5, len(run.actions)))
    else:
        reasons.append("没有可审计的浏览器 Action")
    if not errors:
        score += 15
    else:
        score += max(0, 15 - len(errors) * 5)
        reasons.append(f"执行过程中记录到 {len(errors)} 个错误")
    score = min(100, score)
    retryable = run.success is not True and any(hint in " ".join(errors).lower() for hint in _TRANSIENT_HINTS)
    if run.success is False and not errors:
        retryable = True
    passed = score >= settings.eval_min_score and run.success is not False
    if passed:
        reasons.append("执行质量达到阈值")
    elif retryable:
        reasons.append("错误看起来可通过重新规划/重试恢复")
    else:
        reasons.append("结果未达到质量阈值")
    return AgentEvaluation(score=score, passed=passed, retryable=retryable, reasons=reasons, metrics={"success": run.success, "step_count": run.step_count, "action_count": len(run.actions), "error_count": len(errors), "duration_seconds": round(run.duration_seconds, 3), "result_chars": len(run.final_result), "discovered_jobs": len(run.discovered_jobs)})
