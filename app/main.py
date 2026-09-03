from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .schemas import ApprovalRequest, BrowserTaskRequest, JDParseRequest, JobBatchIngestRequest, MatchRequest, SaveJobRequest
from .services.agent_graph import execute_agent_workflow
from .services.jd_parser import parse_jd
from .services.job_store import ingest_candidates
from .services.resume_matcher import match_resume

app = FastAPI(title=settings.app_name, version="0.2.0")
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
    return {"status": "ok", "version": "0.2.0", "llm_configured": bool(settings.openai_api_key), "browser_agent_configured": bool(settings.browser_use_api_key or settings.openai_api_key), "workflow": "langgraph", "embedding_backend": settings.embedding_model if settings.openai_api_key else "local-feature-hash"}


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


@app.post("/api/tasks")
async def api_create_task(req: BrowserTaskRequest, background_tasks: BackgroundTasks):
    requires_approval = req.task_type == "application" or not req.auto_execute
    task = db.create_task(req.objective, req.task_type, req.model_dump(), requires_approval)
    if not requires_approval:
        background_tasks.add_task(execute_agent_workflow, task["id"])
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
        background_tasks.add_task(execute_agent_workflow, task_id)
    return updated


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
            await websocket.send_json({"type": "status", "data": {"status": task["status"], "retry_count": task["retry_count"], "evaluation": task["evaluation"]}})
            if task["status"] in {"completed", "failed", "rejected"}:
                await websocket.send_json({"type": "done", "data": task})
                return
            await asyncio.sleep(0.75)
    except WebSocketDisconnect:
        return
