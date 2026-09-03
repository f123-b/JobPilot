from __future__ import annotations

from typing import Any

from ..config import settings
from ..schemas import BrowserRunResult, DiscoveredJobs


class BrowserAgentUnavailable(RuntimeError):
    pass


def _safe_call(obj: Any, method: str, default: Any) -> Any:
    fn = getattr(obj, method, None)
    if not callable(fn):
        return default
    try:
        return fn()
    except Exception:
        return default


def _build_llm():
    try:
        if settings.browser_use_api_key:
            from browser_use import ChatBrowserUse
            return ChatBrowserUse(model=settings.browser_model)
        if settings.openai_api_key:
            try:
                from browser_use import ChatOpenAI
            except ImportError:
                from browser_use.llm import ChatOpenAI
            kwargs: dict[str, Any] = {"model": settings.llm_model, "api_key": settings.openai_api_key, "temperature": 0}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            return ChatOpenAI(**kwargs)
    except ImportError as exc:
        raise BrowserAgentUnavailable("browser-use 尚未安装，请执行 pip install -r requirements.txt") from exc
    raise BrowserAgentUnavailable("需要配置 BROWSER_USE_API_KEY 或 OPENAI_API_KEY 才能运行 Browser Agent")


def build_task_prompt(task: dict[str, Any], objective_override: str | None = None) -> str:
    payload = task["payload"]
    objective = objective_override or task["objective"]
    task_type = task["task_type"]
    guardrail = """
安全规则：
1. 不得虚构候选人经历、学历、技能或个人信息。
2. 不得绕过验证码、登录安全校验或网站访问控制。
3. 遇到付款、删除、签署协议等不可逆操作必须停止。
4. 对求职申请任务：只有任务已明确通过人工审批时才允许最终提交。
5. 如果页面信息不足，输出缺失项，不要猜测。
"""
    resume = payload.get("resume_text") or ""
    url = payload.get("job_url") or ""
    context = f"\n目标网址：{url}" if url else ""
    if resume:
        context += f"\n候选人简历（仅可使用其中明确存在的信息）：\n{resume[:12000]}"
    if task_type == "job_search":
        return f"{objective}\n{context}\n搜索岗位并输出结构化岗位列表。每个岗位包含 title, company, location, url, jd_text, source。不要投递；优先返回可直接访问的原始岗位链接。\n{guardrail}"
    if task_type == "application":
        return f"{objective}\n{context}\n本任务已通过人工审批。填写并核对申请；不确定字段不要提交。\n{guardrail}"
    return f"{objective}\n{context}\n完成网页研究任务并返回可核验结果。\n{guardrail}"


async def run_browser_agent(task: dict[str, Any], objective_override: str | None = None) -> BrowserRunResult:
    from browser_use import Agent
    llm = _build_llm()
    prompt = build_task_prompt(task, objective_override)
    kwargs: dict[str, Any] = {"task": prompt, "llm": llm}
    if task["task_type"] == "job_search":
        kwargs["output_model_schema"] = DiscoveredJobs
    agent = Agent(**kwargs)
    history = await agent.run(max_steps=settings.browser_max_steps)
    final_result = _safe_call(history, "final_result", None) or ""
    actions = _safe_call(history, "action_names", []) or []
    errors = _safe_call(history, "errors", []) or []
    success = _safe_call(history, "is_successful", None)
    urls = _safe_call(history, "urls", []) or []
    step_count = int(_safe_call(history, "number_of_steps", 0) or len(actions))
    duration = float(_safe_call(history, "total_duration_seconds", 0.0) or 0.0)
    discovered = []
    if task["task_type"] == "job_search" and final_result:
        try:
            discovered = DiscoveredJobs.model_validate_json(final_result).jobs
        except Exception:
            structured = getattr(history, "structured_output", None)
            if structured:
                try:
                    parsed = structured if isinstance(structured, DiscoveredJobs) else DiscoveredJobs.model_validate(structured)
                    discovered = parsed.jobs
                except Exception:
                    pass
    return BrowserRunResult(success=success, final_result=str(final_result), actions=[str(x) for x in actions], errors=[None if x is None else str(x) for x in errors], urls=[str(x) for x in urls], step_count=step_count, duration_seconds=duration, discovered_jobs=discovered)
