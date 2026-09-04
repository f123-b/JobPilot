from __future__ import annotations

import json
import re
import time
from typing import Any

from ..config import settings
from .usage import estimate_chat_cost, record_usage


class LLMUnavailable(RuntimeError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


async def chat_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise LLMUnavailable("OPENAI_API_KEY is not configured")

    from openai import AsyncOpenAI

    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    client = AsyncOpenAI(**kwargs)
    started = time.perf_counter()
    response = await client.chat.completions.create(
        model=settings.llm_model,
        temperature=0.1,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    duration = time.perf_counter() - started
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
    record_usage(
        component="llm.chat_json",
        model=settings.llm_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=estimate_chat_cost(input_tokens, output_tokens),
        duration_seconds=duration,
        metadata={"response_format": "json"},
    )
    content = response.choices[0].message.content or "{}"
    return extract_json(content)
