"""Evaluation context for policy execution."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EvaluationContext(BaseModel):
    """Facts and available evidence for a policy evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: dict[str, float | str | bool | None] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()
