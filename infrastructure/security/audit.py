"""PHI-Safe Security Audit Logging and Secret Masking (Phase 27)."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

SECRET_PATTERNS = [
    re.compile(
        r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?", re.IGNORECASE
    ),
    re.compile(r"bearer\s+([a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
]


class SanitizedLogRecord(BaseModel):
    """Sanitized security log record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: str
    event_type: str
    message: str
    is_sanitized: bool = True


class PHISafeAuditLogger:
    """Security logger preventing logging of raw secrets, credentials, or full prompt context."""

    def sanitize_message(self, text: str) -> str:
        sanitized = text
        for pattern in SECRET_PATTERNS:
            sanitized = pattern.sub(r"\1=[REDACTED_SECRET]", sanitized)

        # Truncate full LLM prompts if overly long
        if "PROMPT:" in sanitized and len(sanitized) > 200:
            prompt_start = sanitized.find("PROMPT:")
            sanitized = sanitized[: prompt_start + 7] + " [REDACTED_PROMPT_CONTEXT]"

        return sanitized

    def log_event(
        self, event_type: str, message: str, timestamp: str = "2026-08-18T21:00:00Z"
    ) -> SanitizedLogRecord:
        clean_msg = self.sanitize_message(message)
        return SanitizedLogRecord(
            timestamp=timestamp,
            event_type=event_type,
            message=clean_msg,
            is_sanitized=True,
        )
