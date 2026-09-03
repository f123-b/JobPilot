from __future__ import annotations

from ..schemas import BrowserRunResult


def replan_objective(original: str, run: BrowserRunResult, attempt: int) -> str:
    errors = [str(e) for e in run.errors if e]
    failure = "; ".join(errors[-3:]) or "上一轮未成功完成目标"
    return f"{original}\n\n[Retry attempt {attempt}] 上一轮失败信息：{failure[:1200]}\n重新获取当前页面状态，不要复用失效元素；优先使用更直接的导航/搜索路径。如果站点持续阻塞或需要验证码，停止并明确报告原因。"
