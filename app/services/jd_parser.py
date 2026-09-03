from __future__ import annotations

import re
from collections import Counter

from ..schemas import ParsedJD
from .llm import LLMUnavailable, chat_json

SKILLS = ["Python", "C++", "Java", "Go", "JavaScript", "TypeScript", "FastAPI", "Flask", "Django", "LangChain", "LangGraph", "RAG", "MCP", "Agent", "Multi-Agent", "Tool Calling", "Function Calling", "Prompt Engineering", "Embedding", "Vector DB", "FAISS", "Milvus", "Qdrant", "Pinecone", "Chroma", "OpenAI", "Claude", "Gemini", "Llama", "PyTorch", "Transformers", "Docker", "Kubernetes", "Redis", "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Linux", "Git", "CI/CD", "Playwright", "Selenium", "AsyncIO", "REST", "WebSocket", "Kafka", "Elasticsearch", "AWS", "Azure", "GCP"]


def _contains(text: str, skill: str) -> bool:
    if skill.lower() == "agent":
        return bool(re.search(r"\bagent(s)?\b|智能体", text, re.I))
    return skill.lower() in text.lower()


def heuristic_parse(text: str) -> ParsedJD:
    lines = [x.strip(" -•\t") for x in text.splitlines() if x.strip()]
    title = lines[0][:80] if lines else "未知岗位"
    required = [s for s in SKILLS if _contains(text, s)]
    education = next((x for x in ["博士", "硕士", "本科", "大专"] if x in text), None)
    exp_match = re.search(r"(\d+\s*[-~至]\s*\d+|\d+)\s*年", text)
    experience = exp_match.group(0) if exp_match else None
    common_tokens = re.findall(r"[A-Za-z][A-Za-z0-9+.#/-]{2,}|[\u4e00-\u9fff]{2,6}", text)
    keywords = [w for w, _ in Counter(common_tokens).most_common(15)]
    return ParsedJD(title=title, education=education, experience=experience, required_skills=required, preferred_skills=[], responsibilities=lines[1:7], keywords=keywords, summary="本地规则解析结果；配置 OPENAI_API_KEY 后可使用 LLM 结构化解析。")


async def parse_jd(text: str) -> ParsedJD:
    system = """你是招聘JD解析器。只输出JSON，不要Markdown。字段必须包含：
    title, company, location, education, experience, required_skills, preferred_skills,
    responsibilities, keywords, summary。列表字段必须是字符串数组。不要臆造JD中没有的信息。"""
    prompt = f"请结构化解析下面的招聘JD：\n\n{text}"
    try:
        data = await chat_json(system, prompt)
        return ParsedJD.model_validate(data)
    except (LLMUnavailable, Exception):
        return heuristic_parse(text)
