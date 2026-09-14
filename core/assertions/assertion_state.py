"""Append-only state events for assertions."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.assertions.state import AssertionState
from core.identifiers.identifier import Identifier


class AssertionStateEvent(BaseModel):
    """A single, immutable, append-only assertion state change.

    Every transition records the agent, activity, policy version, and reason
    code that produced it, plus a timezone-aware timestamp used for
    deterministic replay.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: Identifier
    assertion_id: Identifier
    from_state: AssertionState | None = None
    to_state: AssertionState
    agent_id: Identifier
    activity_id: Identifier
    policy_version: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)
