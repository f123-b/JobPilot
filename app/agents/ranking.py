from __future__ import annotations

from .. import db
from ..schemas import JobCandidate, RankedJob
from ..services.resume_matcher import heuristic_match


async def rank_candidates(candidates: list[JobCandidate], resume_text: str, top_k: int = 20) -> list[RankedJob]:
    if not resume_text.strip() or not candidates:
        return []

    ranked: list[RankedJob] = []
    for candidate in candidates[:50]:
        jd = candidate.jd_text.strip() or " ".join(
            x for x in [candidate.title, candidate.company or "", candidate.location or ""] if x
        )
        result = await heuristic_match(resume_text, jd)
        ranked.append(
            RankedJob(
                job=candidate,
                score=result.score,
                matched_skills=result.matched_skills,
                missing_skills=result.missing_skills,
                explanation=result.explanation,
            )
        )
        # Upsert keeps the deduplicated job store aligned with the latest ranking score.
        data = candidate.model_dump()
        data["match_score"] = result.score
        db.save_job(data)

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[: max(1, min(top_k, 50))]
