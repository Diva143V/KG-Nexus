"""Generic validation results."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class ValidationSeverity(StrEnum):
    """Severity of a validation finding.

    Distinct from the platform release severity (``PolicySeverity``).
    SHACL native severities are mapped onto these values by adapters;
    they are not the platform's release severity.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class ValidationStatus(StrEnum):
    """Outcome of a single validation check."""

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"
    ERROR = "error"


class ValidationResult(BaseModel):
    """Generic result returned by every validator.

    All five validator interfaces return this same schema, so aggregation
    and release gating never depend on which validator produced a result.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_id: Identifier
    validator: str = Field(min_length=1)
    validator_version: str = Field(min_length=1)
    target: str = Field(min_length=1)
    severity: ValidationSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    status: ValidationStatus
    activity_id: Identifier
