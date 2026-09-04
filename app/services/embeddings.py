from __future__ import annotations

import hashlib
import math
import re
import time
from typing import Iterable

from ..config import settings
from .usage import estimate_embedding_cost, record_usage

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.#/-]{1,}|[\u4e00-\u9fff]{2,6}")


def _tokens(text: str) -> Iterable[str]:
    for token in _TOKEN_RE.findall(text.lower()):
        yield token


def local_hash_embedding(text: str, dim: int | None = None) -> list[float]:
    dim = dim or settings.local_embedding_dim
    vec = [0.0] * dim
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        idx = value % dim
        sign = 1.0 if (value >> 1) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


async def embed_text(text: str) -> tuple[list[float], str]:
    if settings.openai_api_key:
        try:
            from openai import AsyncOpenAI

            kwargs = {"api_key": settings.openai_api_key}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            client = AsyncOpenAI(**kwargs)
            started = time.perf_counter()
            response = await client.embeddings.create(model=settings.embedding_model, input=text[:24000])
            duration = time.perf_counter() - started
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "prompt_tokens", 0) or getattr(usage, "total_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", input_tokens) or input_tokens)
            record_usage(
                component="embedding",
                model=settings.embedding_model,
                input_tokens=input_tokens,
                total_tokens=total_tokens,
                cost_usd=estimate_embedding_cost(input_tokens),
                duration_seconds=duration,
            )
            return list(response.data[0].embedding), settings.embedding_model
        except Exception:
            pass
    return local_hash_embedding(text), "local-feature-hash"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
