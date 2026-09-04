import asyncio

from app import db
from app.agents.planner import heuristic_plan
from app.agents.ranking import rank_candidates
from app.config import settings
from app.memory.store import remember_job, set_user_preference
from app.rag.chunking import chunk_resume_text
from app.rag.document_parser import parse_document_bytes
from app.rag.resume_rag import index_resume_text, retrieve_resume_evidence
from app.schemas import JobCandidate


def _swap_settings(tmp_path):
    original = {
        "database_path": settings.database_path,
        "vector_backend": settings.vector_backend,
        "postgres_url": settings.postgres_url,
        "local_embedding_dim": settings.local_embedding_dim,
        "vector_dim": settings.vector_dim,
    }
    object.__setattr__(settings, "database_path", tmp_path / "rag-test.db")
    object.__setattr__(settings, "vector_backend", "sqlite")
    object.__setattr__(settings, "postgres_url", None)
    object.__setattr__(settings, "local_embedding_dim", 128)
    object.__setattr__(settings, "vector_dim", 128)
    return original


def _restore_settings(original):
    for key, value in original.items():
        object.__setattr__(settings, key, value)


def test_resume_chunking_and_text_parser():
    text = "项目经历\nJobPilot：使用 Python LangGraph 构建 Agent。\n专业技能\nFastAPI Docker RAG pgvector"
    assert "LangGraph" in parse_document_bytes("resume.txt", text.encode())
    chunks = chunk_resume_text(text, max_chars=120)
    assert len(chunks) >= 2
    assert any(chunk.section == "项目经历" for chunk in chunks)


def test_resume_rag_index_and_retrieval(tmp_path):
    original = _swap_settings(tmp_path)
    try:
        db.init_db()
        result = asyncio.run(index_resume_text(
            user_id="u1",
            filename="resume.txt",
            text=(
                "项目经历\n使用 Python、LangGraph、FastAPI 开发多智能体 JobPilot，加入 RAG 与 pgvector。\n"
                "专业技能\nSTM32 FreeRTOS CAN MQTT。"
            ),
        ))
        rows = asyncio.run(retrieve_resume_evidence(
            "u1", "AI Agent Engineer requires Python LangGraph RAG FastAPI", top_k=3, source_id=result.source_id
        ))
        assert result.chunk_count >= 2
        assert rows
        assert any("LangGraph" in row.content for row in rows)
        assert rows[0].source_id == result.source_id
    finally:
        _restore_settings(original)


def test_planner_accepts_preindexed_resume():
    plan = heuristic_plan({
        "objective": "Find Agent jobs",
        "task_type": "job_search",
        "payload": {"resume_source_id": "resume.txt:abc123"},
    })
    assert [x.agent for x in plan.steps] == ["resume", "search", "ranking", "evaluate"]


def test_long_term_memory_influences_ranking(tmp_path):
    original = _swap_settings(tmp_path)
    try:
        db.init_db()
        resume = "Python LangGraph Agent FastAPI Docker RAG developer"
        indexed = asyncio.run(index_resume_text(user_id="u2", filename="resume.txt", text=resume))
        candidate = JobCandidate(
            title="AI Agent Engineer", company="Example", location="Shanghai",
            url="https://example.com/1", jd_text="Python LangGraph Agent FastAPI Docker RAG",
        )
        set_user_preference("u2", "target_location", "Shanghai")
        baseline = asyncio.run(rank_candidates(
            [candidate], resume, user_id="u2", resume_source_id=indexed.source_id,
            preferences={"target_location": "Shanghai"},
        ))[0]
        remember_job("u2", candidate.model_dump(), "rejected", "not interested")
        rejected = asyncio.run(rank_candidates(
            [candidate], resume, user_id="u2", resume_source_id=indexed.source_id,
            preferences={"target_location": "Shanghai"},
        ))[0]
        assert baseline.evidence
        assert baseline.score > rejected.score
        assert rejected.memory_status == "rejected"
    finally:
        _restore_settings(original)
