from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class FailureInfo:
    category: str
    retryable: bool
    severity: str
    reason: str

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


_RULES: list[tuple[str, tuple[str, ...], bool, str]] = [
    ("captcha", ("captcha", "验证码", "recaptcha", "hcaptcha"), False, "warning"),
    ("auth", ("unauthorized", "forbidden", "login required", "sign in", "401", "403", "未登录", "登录"), False, "warning"),
    ("rate_limit", ("rate limit", "too many requests", "429"), True, "warning"),
    ("timeout", ("timeout", "timed out", "deadline exceeded"), True, "warning"),
    ("network", ("connection reset", "connection refused", "network", "dns", "502", "503", "504"), True, "warning"),
    ("element", ("element not found", "stale element", "selector", "locator", "not clickable"), True, "info"),
    ("safety_block", ("approval required", "irreversible", "payment", "安全规则", "not allowed"), False, "warning"),
    ("validation", ("validation", "invalid", "missing field", "schema", "parse"), False, "info"),
    ("model", ("model", "llm", "openai", "context length", "token limit"), True, "warning"),
]


def classify_failure(errors: Iterable[str | None] | str | None) -> FailureInfo:
    if errors is None:
        text = ""
    elif isinstance(errors, str):
        text = errors
    else:
        text = " ".join(str(x) for x in errors if x)
    normalized = text.lower().strip()
    if not normalized:
        return FailureInfo("none", False, "info", "no explicit error text")
    for category, hints, retryable, severity in _RULES:
        if any(hint in normalized for hint in hints):
            return FailureInfo(category, retryable, severity, f"matched {category} failure signature")
    return FailureInfo("unknown", False, "warning", "unclassified execution failure")
