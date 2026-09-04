from __future__ import annotations

import hashlib
from typing import Any

from ..schemas import ResumeEvidence, ResumeIndexResult
from .chunking import chunk_resume_text
from .vector_store import resume_vector_store


def make_source_id(filename: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    stem = (filename or "resume").replace(" ", "_")[:60]
    return f"{stem}:{digest}"


async def index_resume_text(
    *, user_id: str, text: str, filename: str = "resume.txt", metadata: dict[str, Any] | None = None,
) -> ResumeIndexResult:
    chunks = chunk_resume_text(text)
    source_id = make_source_id(filename, text)
    result = await resume_vector_store.replace_chunks(
        user_id=user_id,
        source_id=source_id,
        chunks=chunks,
        metadata={"filename": filename, **(metadata or {})},
    )
    return ResumeIndexResult(
        user_id=user_id,
        source_id=source_id,
        chunk_count=len(chunks),
        vector_backend=result["backend"],
    )


async def retrieve_resume_evidence(
    user_id: str, query: str, top_k: int = 5, source_id: str | None = None
) -> list[ResumeEvidence]:
    rows = await resume_vector_store.search(user_id=user_id, query=query, top_k=top_k, source_id=source_id)
    return [
        ResumeEvidence(
            source_id=row.source_id,
            section=row.section,
            content=row.content,
            score=max(0.0, min(1.0, row.score)),
        )
        for row in rows
    ]
