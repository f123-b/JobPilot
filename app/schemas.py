from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class JDParseRequest(BaseModel):
    text: str = Field(min_length=20)


class ParsedJD(BaseModel):
    title: str = "未知岗位"
    company: str | None = None
    location: str | None = None
    education: str | None = None
    experience: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    summary: str = ""


class MatchRequest(BaseModel):
    resume_text: str = Field(min_length=20)
    jd_text: str = Field(min_length=20)


class MatchResult(BaseModel):
    score: int = Field(ge=0, le=100)
    skill_score: int = Field(default=0, ge=0, le=100)
    semantic_score: int = Field(default=0, ge=0, le=100)
    matched_skills: list[str]
    missing_skills: list[str]
    strengths: list[str]
    risks: list[str]
    suggestions: list[str]
    explanation: str


class SaveJobRequest(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    url: str | None = None
    jd_text: str
    source: str | None = None
    match_score: int | None = Field(default=None, ge=0, le=100)


class JobCandidate(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    url: str | None = None
    jd_text: str = ""
    source: str | None = None


class DiscoveredJobs(BaseModel):
    jobs: list[JobCandidate] = Field(default_factory=list)


class JobBatchIngestRequest(BaseModel):
    jobs: list[JobCandidate] = Field(min_length=1, max_length=100)


class AgentPlanStep(BaseModel):
    agent: Literal["resume", "search", "ranking", "browser", "evaluate"]
    objective: str = Field(min_length=3)


class AgentPlan(BaseModel):
    goal: str
    rationale: str = ""
    steps: list[AgentPlanStep] = Field(default_factory=list)
    planner_backend: Literal["llm", "heuristic"] = "heuristic"


class ResumeProfile(BaseModel):
    skills: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    experience_years: int | None = None
    keywords: list[str] = Field(default_factory=list)
    summary: str = ""


class ResumeEvidence(BaseModel):
    source_id: str
    section: str
    content: str
    score: float = Field(ge=0.0, le=1.0)


class ResumeIndexResult(BaseModel):
    user_id: str
    source_id: str
    chunk_count: int
    vector_backend: str


class RankedJob(BaseModel):
    job: JobCandidate
    score: int = Field(ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence: list[ResumeEvidence] = Field(default_factory=list)
    memory_status: str | None = None
    explanation: str = ""


class BrowserTaskRequest(BaseModel):
    objective: str = Field(min_length=10)
    task_type: Literal["research", "job_search", "application"] = "research"
    user_id: str = Field(default="default", min_length=1, max_length=120)
    resume_text: str | None = None
    resume_source_id: str | None = None
    job_url: str | None = None
    auto_execute: bool = False


class ApprovalRequest(BaseModel):
    approved: bool
    note: str | None = None


class AgentEvaluation(BaseModel):
    score: int = Field(ge=0, le=100)
    passed: bool
    retryable: bool
    reasons: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | bool | str | None] = Field(default_factory=dict)


class BrowserRunResult(BaseModel):
    success: bool | None = None
    final_result: str = ""
    actions: list[str] = Field(default_factory=list)
    errors: list[str | None] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    step_count: int = 0
    duration_seconds: float = 0.0
    discovered_jobs: list[JobCandidate] = Field(default_factory=list)


class ResumeSearchRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=120)
    source_id: str | None = None
    query: str = Field(min_length=3)
    top_k: int = Field(default=5, ge=1, le=20)


class UserMemoryRequest(BaseModel):
    value: Any


class JobMemoryRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=120)
    job_id: int
    status: Literal["seen", "saved", "applied", "rejected", "interview", "offer"]
    note: str | None = None
