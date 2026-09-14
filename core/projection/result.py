"""Projection results: backend-independent outcomes of projection steps."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProjectionResult(BaseModel):
    """Outcome of building a projection in a backend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    backend_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    record_count: int = Field(ge=0)


class ProjectionValidationResult(BaseModel):
    """Outcome of validating a projection in a backend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    passed: bool
    errors: tuple[str, ...] = Field(default_factory=tuple)
