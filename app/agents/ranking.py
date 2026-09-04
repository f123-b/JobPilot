from __future__ import annotations

from .. import db
from ..memory.store import get_job_memory
from ..rag.resume_rag import retrieve_resume_evidence
from ..schemas import JobCandidate, RankedJob
from ..services.resume_matcher import heuristic_match
from typing import Any


async def rank_candidates(
    candidates: list[JobCandidate],
    resume_text: str,
    *,
    user_id: str = "default",
    use_rag: bool = True,
    preferences: dict[str, Any] | None = None,
    resume_source_id: str | None = None,
    top_k: int = 20,
) -> list[RankedJob]:
    if not candidates:
        return []

    ranked: list[RankedJob] = []
    for candidate in candidates[:50]:
        jd = candidate.jd_text.strip() or " ".join(
            x for x in [candidate.title, candidate.company or "", candidate.location or ""] if x
        )
        evidence = await retrieve_resume_evidence(
            user_id, jd, top_k=4, source_id=resume_source_id
        ) if use_rag else []
        evidence_text = "\n".join(item.content for item in evidence).strip()
        grounding_text = evidence_text or resume_text
        if not grounding_text:
            continue

        result = await heuristic_match(grounding_text, jd)
        retrieval_score = int(round(100 * (sum(x.score for x in evidence) / len(evidence)))) if evidence else result.semantic_score
        score = int(round(result.score * 0.85 + retrieval_score * 0.15))

        fingerprint = db.job_fingerprint(candidate.model_dump())
        memory = get_job_memory(user_id, fingerprint)
        memory_status = memory.get("status") if memory else None
        if memory_status == "rejected":
            score = max(0, score - 25)

        preferences = preferences or {}
        preferred_location = str(preferences.get("location") or preferences.get("target_location") or "").strip().lower()
        if preferred_location and preferred_location in (candidate.location or "").lower():
            score = min(100, score + 5)

        explanation = result.explanation
        if evidence:
            explanation += f" Retrieved {len(evidence)} resume evidence chunks (avg similarity {retrieval_score}%)."
        if preferred_location and preferred_location in (candidate.location or "").lower():
            explanation += " Persistent location preference matched."
        if memory_status:
            explanation += f" Existing job memory status: {memory_status}."

        ranked.append(
            RankedJob(
                job=candidate,
                score=max(0, min(100, score)),
                matched_skills=result.matched_skills,
                missing_skills=result.missing_skills,
                evidence=evidence,
                memory_status=memory_status,
                explanation=explanation,
            )
        )
        data = candidate.model_dump()
        data["match_score"] = max(0, min(100, score))
        db.save_job(data)

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[: max(1, min(top_k, 50))]
