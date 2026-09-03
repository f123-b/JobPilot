import asyncio

from app import db
from app.agents.planner import heuristic_plan
from app.agents.resume import build_resume_profile
from app.schemas import BrowserRunResult, JobCandidate
from app.workflow import multi_agent_graph as workflow


def test_planner_job_search_builds_specialist_sequence():
    task = {
        "objective": "Find AI Agent jobs in Shanghai",
        "task_type": "job_search",
        "payload": {"resume_text": "Python LangGraph Agent FastAPI Docker"},
    }
    plan = heuristic_plan(task)
    assert [x.agent for x in plan.steps] == ["resume", "search", "ranking", "evaluate"]


def test_planner_application_uses_browser_and_evaluate():
    task = {
        "objective": "Review and prepare this job application",
        "task_type": "application",
        "payload": {"resume_text": "Python developer"},
    }
    plan = heuristic_plan(task)
    assert [x.agent for x in plan.steps] == ["resume", "browser", "evaluate"]


def test_resume_agent_extracts_explicit_evidence_only():
    profile = build_resume_profile(
        "AI应用开发工程师\n使用 Python + LangGraph 开发 Agent，FastAPI 提供接口。\n"
        "项目使用 Docker 部署，并实现 RAG 检索增强。"
    )
    assert "Python" in profile.skills
    assert "LangGraph" in profile.skills
    assert "Agent" in profile.skills
    assert "Docker" in profile.skills
    assert profile.evidence


def test_fallback_multi_agent_workflow_routes_search_ranking_evaluate(tmp_path):
    original_path = db.settings.database_path
    object.__setattr__(db.settings, "database_path", tmp_path / "jobpilot-test.db")
    try:
        db.init_db()
        task = db.create_task(
            "Find AI Agent Engineer jobs in Shanghai",
            "job_search",
            {
                "objective": "Find AI Agent Engineer jobs in Shanghai",
                "task_type": "job_search",
                "resume_text": "Python LangGraph Agent FastAPI Docker RAG",
                "job_url": None,
                "auto_execute": True,
            },
            requires_approval=False,
        )

        async def fake_search(_task, _objective):
            return BrowserRunResult(
                success=True,
                final_result="Found one structured job",
                actions=["search", "extract"],
                errors=[],
                step_count=2,
                discovered_jobs=[
                    JobCandidate(
                        title="AI Agent Engineer",
                        company="Example AI",
                        location="Shanghai",
                        url="https://example.com/jobs/agent-1",
                        jd_text="Required: Python, LangGraph, Agent, FastAPI, Docker, RAG",
                        source="company-site",
                    )
                ],
            )

        original_search = workflow.run_search_agent
        workflow.run_search_agent = fake_search
        try:
            asyncio.run(workflow._fallback_workflow(task["id"]))
        finally:
            workflow.run_search_agent = original_search

        finished = db.get_task(task["id"])
        assert finished["status"] == "completed"
        assert finished["plan"]["planner_backend"] == "heuristic"
        assert finished["workflow"]["ranked_count"] == 1
        events = [x["event_type"] for x in db.list_traces(task["id"])]
        assert "planner_plan" in events
        assert "resume_agent_result" in events
        assert "search_agent_result" in events
        assert "ranking_agent_result" in events
        assert "evaluation" in events
        assert "graph_finish" in events
    finally:
        object.__setattr__(db.settings, "database_path", original_path)
