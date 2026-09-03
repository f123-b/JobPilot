import asyncio

from app.services.embeddings import cosine_similarity, local_hash_embedding
from app.services.resume_matcher import heuristic_match


def test_embedding_similarity_identity():
    a = local_hash_embedding("Python LangGraph Agent FastAPI")
    b = local_hash_embedding("Python LangGraph Agent FastAPI")
    assert cosine_similarity(a, b) > 0.99


def test_matcher_prefers_skill_overlap():
    resume = "Python developer. Built LangGraph Agent with FastAPI, Docker and RAG."
    jd = "AI Agent Engineer\nRequired: Python, LangGraph, FastAPI, Docker, RAG, MCP"
    result = asyncio.run(heuristic_match(resume, jd))
    assert result.score >= 40
    assert "Python" in result.matched_skills
    assert "MCP" in result.missing_skills
    assert 0 <= result.semantic_score <= 100
