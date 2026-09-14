"""Output guardrails — PII and secret scanning for final answers.

Defense in depth: even if data leaks into a model answer, the perimeter
strips it before it reaches the client. Inspired by the ingress/egress
perimeter plane from the DataHek prototype.
"""
import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("connection_string", re.compile(r"\b\w+://[^:@\s]+:[^@\s]+@")),
    ("api_key", re.compile(r"\b(?:sk-[A-Za-z0-9]{10,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9-]{10,})\b")),
    ("token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{12,}\b")),
    ("password", re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]

_LABELS = {
    "email": "[EMAIL]",
    "phone": "[PHONE]",
    "card": "[CARD]",
    "ssn": "[SSN]",
    "api_key": "[API_KEY]",
    "token": "[TOKEN]",
    "password": r"\1=[REDACTED]",
    "connection_string": "[CONNECTION_STRING]",
}


def sanitize_output(text: str) -> tuple[str, list[str]]:
    """Redact PII/secrets; returns (clean_text, sorted unique categories found)."""
    if not text:
        return text, []
    findings: set[str] = set()
    for category, pattern in _PATTERNS:
        text, count = pattern.subn(_LABELS[category], text)
        if count:
            findings.add(category)
    return text, sorted(findings)


def redact_pii(text: str) -> str:
    """Back-compat wrapper: redact emails/phones (and any other sensitive pattern)."""
    return sanitize_output(text)[0]
