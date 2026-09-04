from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .schemas import (
    ApprovalRequest, BrowserTaskRequest, JDParseRequest, JobBatchIngestRequest, JobMemoryRequest,
    MatchRequest, ResumeSearchRequest, SaveJobRequest, UserMemoryRequest,
)
from .agents.planner import build_plan
from .workflow.multi_agent_graph import execute_multi_agent_workflow
from .services.jd_parser import parse_jd
from .services.job_store import ingest_candidates
from .services.resume_matcher import match_resume
from .rag.document_parser import UnsupportedDocumentError, parse_document_bytes
from .rag.resume_rag import index_resume_text, retrieve_resume_evidence
from .memory.store import get_user_preferences, remember_job, set_user_preference

app = FastAPI(title=settings.app_name, version="0.3.2")
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup() -> None:
    db.init_db()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": "0.3.2",
        "llm_configured": bool(settings.openai_api_key),
        "browser_agent_configured": bool(settings.browser_use_api_key or settings.openai_api_key),
        "workflow": "langgraph-multi-agent",
        "agents": ["planner", "resume", "search", "ranking", "browser", "evaluate"],
        "embedding_backend": settings.embedding_model if settings.openai_api_key else "local-feature-hash",
        "vector_backend": settings.vector_backend if settings.postgres_url else "sqlite-local-vector",
        "checkpoint_backend": settings.checkpoint_backend if settings.postgres_url else "sqlite",
        "rag": "resume-evidence",
    }


@app.post("/api/jd/parse")
async def api_parse_jd(req: JDParseRequest):
    return await parse_jd(req.text)


@app.post("/api/match")
async def api_match(req: MatchRequest):
    return await match_resume(req.resume_text, req.jd_text)


@app.post("/api/jobs")
def api_save_job(req: SaveJobRequest):
    return db.save_job(req.model_dump())


@app.post("/api/jobs/ingest")
def api_ingest_jobs(req: JobBatchIngestRequest):
    return ingest_candidates(req.jobs)


@app.get("/api/jobs")
def api_list_jobs(limit: int = 100):
    return db.list_jobs(min(max(limit, 1), 500))


@app.get("/api/agents")
def api_agents():
    return {
        "agents": [
            {"name": "planner", "role": "decompose goal and choose safe agent sequence"},
            {"name": "resume", "role": "extract evidence-grounded candidate profile"},
            {"name": "search", "role": "discover structured job candidates with Browser Use"},
            {"name": "ranking", "role": "rank candidates against resume evidence"},
            {"name": "browser", "role": "execute research or approved application workflow"},
            {"name": "evaluate", "role": "quality gate and retry decision"},
        ]
    }


@app.post("/api/plan")
async def api_preview_plan(req: BrowserTaskRequest):
    task = {
        "objective": req.objective,
        "task_type": req.task_type,
        "payload": req.model_dump(),
    }
    return await build_plan(task)


@app.post("/api/resume/index")
async def api_index_resume(request: Request, user_id: str = "default", filename: str = "resume.txt"):
    # Accept raw document bytes to keep the core server free from multipart-only runtime requirements.
    # Example: curl --data-binary @resume.pdf '?user_id=u1&filename=resume.pdf'
    content = await request.body()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "resume file too large; max 5 MB")
    try:
        text = parse_document_bytes(filename, content)
    except UnsupportedDocumentError as exc:
        raise HTTPException(415, str(exc)) from exc
    if len(text.strip()) < 20:
        raise HTTPException(400, "resume parser returned too little text")
    result = await index_resume_text(user_id=user_id, text=text, filename=filename)
    return {**result.model_dump(), "text_chars": len(text)}


@app.post("/api/resume/search")
async def api_search_resume(req: ResumeSearchRequest):
    return {"results": [x.model_dump() for x in await retrieve_resume_evidence(req.user_id, req.query, req.top_k, req.source_id)]}


@app.get("/api/memory/users/{user_id}")
def api_get_user_memory(user_id: str):
    return {"user_id": user_id, "preferences": get_user_preferences(user_id), "jobs": db.list_job_memory(user_id)}


@app.put("/api/memory/users/{user_id}/{key}")
def api_set_user_memory(user_id: str, key: str, req: UserMemoryRequest):
    return set_user_preference(user_id, key, req.value)


@app.post("/api/memory/jobs")
def api_set_job_memory(req: JobMemoryRequest):
    job = db.get_job(req.job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return remember_job(req.user_id, job, req.status, req.note)


@app.post("/api/tasks")
async def api_create_task(req: BrowserTaskRequest, background_tasks: BackgroundTasks):
    # Application has external side effects, so it always requires human approval.
    requires_approval = req.task_type == "application" or not req.auto_execute
    task = db.create_task(req.objective, req.task_type, req.model_dump(), requires_approval)
    if not requires_approval:
        background_tasks.add_task(execute_multi_agent_workflow, task["id"])
    return task


@app.post("/api/tasks/{task_id}/approve")
async def api_approve_task(task_id: int, req: ApprovalRequest, background_tasks: BackgroundTasks):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if not task["requires_approval"]:
        raise HTTPException(400, "task does not require approval")
    updated = db.approve_task(task_id, req.approved, req.note)
    if req.approved:
        background_tasks.add_task(execute_multi_agent_workflow, task_id)
    return updated


@app.post("/api/tasks/{task_id}/resume")
async def api_resume_task(task_id: int, background_tasks: BackgroundTasks):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if task["requires_approval"] and task["approved"] is not True:
        raise HTTPException(409, "task still requires approval")
    if task["status"] == "completed":
        raise HTTPException(409, "completed task does not need resume")
    db.update_task(task_id, status="queued", error_text=None)
    db.add_trace(task_id, "workflow_resume_requested", {"thread_id": task.get("workflow_thread_id")})
    background_tasks.add_task(execute_multi_agent_workflow, task_id)
    return db.get_task(task_id)


@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: int):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    task["traces"] = db.list_traces(task_id)
    return task


@app.websocket("/ws/tasks/{task_id}")
async def ws_task_trace(websocket: WebSocket, task_id: int):
    if not db.get_task(task_id):
        await websocket.close(code=4404)
        return
    await websocket.accept()
    last_id = 0
    try:
        while True:
            for trace in db.list_traces(task_id, after_id=last_id):
                last_id = max(last_id, trace["id"])
                await websocket.send_json({"type": "trace", "data": trace})
            task = db.get_task(task_id)
            await websocket.send_json({"type": "status", "data": {
                "status": task["status"],
                "retry_count": task["retry_count"],
                "current_agent": task.get("current_agent"),
                "workflow": task.get("workflow"),
                "plan": task.get("plan"),
                "evaluation": task["evaluation"],
            }})
            if task["status"] in {"completed", "failed", "rejected"}:
                await websocket.send_json({"type": "done", "data": task})
                return
            await asyncio.sleep(0.75)
    except WebSocketDisconnect:
        return
