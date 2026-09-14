"""Validation context."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ValidationContext(BaseModel):
    """Data and evidence available to validators for one target.

    Validators read from this context; they never mutate the platform.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: str = Field(min_length=1)
    data: dict[str, object] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()
