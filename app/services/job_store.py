from __future__ import annotations

from typing import Iterable

from .. import db
from ..schemas import JobCandidate


def ingest_candidates(candidates: Iterable[JobCandidate]) -> dict:
    items = [candidate.model_dump() for candidate in candidates]
    return db.ingest_jobs(items)
