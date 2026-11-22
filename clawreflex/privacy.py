"""Fail-closed provider disclosure filter and secret-safe diagnostics."""
from __future__ import annotations

import re
from dataclasses import dataclass

PATTERNS = (
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
    re.compile(r'(?im)^[ \t]*(?:export[ \t]+)?(?:[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD))\s*[:=]\s*[\"\']?([^\s\"\'#,;]{4,})'),
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
)


@dataclass(frozen=True)
class Redaction:
    text: str
    count: int


def redact(source: str, extra_patterns: tuple[str, ...] = ()) -> Redaction:
    if not isinstance(source, str):
        raise ValueError('provider payload must be text')
    count = 0
    for pattern in (*PATTERNS, *(re.compile(value) for value in extra_patterns)):
        def replacement(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            if match.lastindex:
                start, end = match.span(1)
                return match.group(0)[:start - match.start()] + '[REDACTED]' + match.group(0)[end - match.start():]
            return '[REDACTED]'
        source = pattern.sub(replacement, source)
    return Redaction(source, count)


def provider_source(source: str, extra_patterns: tuple[str, ...] = ()) -> str:
    """Return sanitized source. Caller must block apply if redaction changes semantics."""
    return redact(source, extra_patterns).text
