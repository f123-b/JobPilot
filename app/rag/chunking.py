from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    section: str
    content: str


_SECTION_RE = re.compile(
    r"^(个人信息|教育经历|教育背景|工作经历|实习经历|项目经历|项目经验|专业技能|技能|获奖|证书|自我评价|education|experience|projects?|skills?|summary)\s*[:：]?$",
    re.IGNORECASE,
)


def _sectioned_lines(text: str) -> list[tuple[str, str]]:
    section = "resume"
    items: list[tuple[str, str]] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip(" \t•·-—")
        if not line:
            continue
        if _SECTION_RE.match(line):
            section = line.rstrip(":：").lower()
            continue
        items.append((section, line))
    return items


def chunk_resume_text(text: str, max_chars: int = 650, overlap_chars: int = 120) -> list[TextChunk]:
    """Chunk resume text while keeping section labels and small overlap.

    Resume documents are short and highly structured, so section-aware chunking works
    better than blindly splitting every N characters. Very long lines are windowed.
    """
    text = text.strip()
    if not text:
        return []

    grouped: list[tuple[str, list[str]]] = []
    for section, line in _sectioned_lines(text):
        if not grouped or grouped[-1][0] != section:
            grouped.append((section, [line]))
        else:
            grouped[-1][1].append(line)

    chunks: list[TextChunk] = []
    index = 0
    for section, lines in grouped or [("resume", [text])]:
        buffer = ""
        for line in lines:
            candidate = f"{buffer}\n{line}".strip() if buffer else line
            if len(candidate) <= max_chars:
                buffer = candidate
                continue
            if buffer:
                chunks.append(TextChunk(index, section, buffer))
                index += 1
                tail = buffer[-overlap_chars:] if overlap_chars else ""
                buffer = f"{tail}\n{line}".strip()
            else:
                start = 0
                while start < len(line):
                    part = line[start : start + max_chars]
                    chunks.append(TextChunk(index, section, part))
                    index += 1
                    start += max(1, max_chars - overlap_chars)
                buffer = ""
        if buffer:
            chunks.append(TextChunk(index, section, buffer))
            index += 1

    return chunks
