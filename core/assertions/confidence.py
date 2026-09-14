"""Confidence scores attached to assertions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceMethod(StrEnum):
    """How a confidence score was produced."""

    MANUAL = "manual"
    STATISTICAL = "statistical"
    MODEL = "model"
    UNSPECIFIED = "unspecified"


class Confidence(BaseModel):
    """A score describing how much an assertion is believed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float = Field(ge=0, le=1)
    method: ConfidenceMethod = ConfidenceMethod.UNSPECIFIED
    source: str | None = None
