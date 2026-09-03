from __future__ import annotations

import re
from collections import Counter

from ..schemas import ResumeProfile

_SKILLS = [
    "Python", "C", "C++", "Java", "JavaScript", "TypeScript", "FastAPI", "Flask", "Django",
    "LangChain", "LangGraph", "RAG", "Agent", "MCP", "OpenAI", "LLM", "Embedding", "Qdrant",
    "pgvector", "PostgreSQL", "SQLite", "Redis", "Docker", "Kubernetes", "Linux", "Git",
    "PyTorch", "Transformers", "OpenCV", "ROS2", "STM32", "FreeRTOS", "CAN", "MQTT",
]


def _has(text: str, skill: str) -> bool:
    lower = text.lower()
    aliases = {
        "Agent": ["agent", "智能体"],
        "C++": ["c++", "cpp"],
        "C": [" c ", "c语言"],
        "RAG": ["rag", "检索增强"],
        "MCP": ["mcp", "model context protocol"],
    }
    keys = aliases.get(skill, [skill.lower()])
    padded = f" {lower} "
    return any(key in padded for key in keys)


def build_resume_profile(resume_text: str) -> ResumeProfile:
    text = resume_text.strip()
    skills = [skill for skill in _SKILLS if _has(text, skill)]

    # Keep this extraction conservative: project/experience evidence remains verbatim snippets.
    lines = [re.sub(r"\s+", " ", x).strip(" -•\t") for x in text.splitlines()]
    evidence = [x for x in lines if len(x) >= 18][:12]
    years = re.findall(r"(?<!\d)(\d{1,2})\s*年", text)
    experience_years = max((int(x) for x in years), default=None)

    keywords = re.findall(r"[A-Za-z][A-Za-z0-9+.#/-]{1,}", text)
    common = [token for token, _ in Counter(x.lower() for x in keywords).most_common(12)]
    return ResumeProfile(
        skills=skills,
        evidence=evidence,
        experience_years=experience_years,
        keywords=common,
        summary=f"Extracted {len(skills)} explicit skills and {len(evidence)} evidence snippets from the supplied resume.",
    )
