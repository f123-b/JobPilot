from __future__ import annotations

from ..schemas import MatchResult
from .embeddings import cosine_similarity, embed_text
from .jd_parser import heuristic_parse
from .llm import LLMUnavailable, chat_json


def _skill_overlap(resume_text: str, jd_text: str) -> tuple[list[str], list[str], int]:
    parsed = heuristic_parse(jd_text)
    req = parsed.required_skills
    resume_lower = resume_text.lower()
    matched = [s for s in req if s.lower() in resume_lower or (s == "Agent" and "智能体" in resume_text)]
    missing = [s for s in req if s not in matched]
    score = 70 if not req else round(len(matched) / len(req) * 100)
    return matched, missing, score


async def heuristic_match(resume_text: str, jd_text: str) -> MatchResult:
    matched, missing, skill_score = _skill_overlap(resume_text, jd_text)
    resume_vec, embedding_backend = await embed_text(resume_text)
    jd_vec, _ = await embed_text(jd_text)
    cosine = max(0.0, cosine_similarity(resume_vec, jd_vec))
    semantic_score = round(cosine * 100)
    score = min(100, round(skill_score * 0.7 + semantic_score * 0.3))
    strengths = matched[:8] or ["简历与JD存在基础语义重合"]
    risks = [f"缺少明确证据：{x}" for x in missing[:6]]
    suggestions = [f"若确有项目经历，在简历中补充 {x} 的具体使用场景与结果" for x in missing[:5]]
    if not suggestions:
        suggestions = ["补充量化指标、系统规模、延迟/准确率/吞吐等可验证结果"]
    return MatchResult(score=score, skill_score=skill_score, semantic_score=semantic_score, matched_skills=matched, missing_skills=missing, strengths=strengths, risks=risks, suggestions=suggestions, explanation=f"本地匹配：技能覆盖70% + Embedding相似度30%；Embedding后端={embedding_backend}。")


async def match_resume(resume_text: str, jd_text: str) -> MatchResult:
    base = await heuristic_match(resume_text, jd_text)
    system = """你是严谨的AI岗位简历匹配器。只输出JSON。必须基于简历中的具体经历证据。
字段：score(0-100整数), matched_skills, missing_skills, strengths, risks, suggestions, explanation。
不得建议伪造经历；缺失能力只能建议学习、实践或在确有经历时补充证据。"""
    prompt = f"JD:\n{jd_text}\n\n简历:\n{resume_text}\n\n程序计算的技能分={base.skill_score}，语义Embedding分={base.semantic_score}。请结合证据校准总分。"
    try:
        data = await chat_json(system, prompt)
        data["skill_score"] = base.skill_score
        data["semantic_score"] = base.semantic_score
        return MatchResult.model_validate(data)
    except (LLMUnavailable, Exception):
        return base
