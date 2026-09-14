"""Validation reports and release gates."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from core.validation.result import ValidationResult, ValidationSeverity, ValidationStatus


class GateOutcome(StrEnum):
    """Outcome of the release gate for a target."""

    PASS = "pass"
    REVIEW = "review"
    BLOCKED = "blocked"


class ValidationReport(BaseModel):
    """Immutable aggregation of validation results for one target.

    The ``gate`` is the release-gate outcome derived deterministically
    from the aggregated results.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: str = Field(min_length=1)
    results: tuple[ValidationResult, ...]
    gate: GateOutcome

    @property
    def blockers(self) -> tuple[ValidationResult, ...]:
        """FAIL results whose severity is BLOCKER."""
        return tuple(
            result
            for result in self.results
            if result.status is ValidationStatus.FAIL
            and result.severity is ValidationSeverity.BLOCKER
        )

    @property
    def errors(self) -> tuple[ValidationResult, ...]:
        """FAIL results whose severity is ERROR."""
        return tuple(
            result
            for result in self.results
            if result.status is ValidationStatus.FAIL
            and result.severity is ValidationSeverity.ERROR
        )

    @property
    def warnings(self) -> tuple[ValidationResult, ...]:
        """Results whose severity is WARNING."""
        return tuple(
            result for result in self.results if result.severity is ValidationSeverity.WARNING
        )

    @property
    def passed(self) -> bool:
        """Whether the release gate passed."""
        return self.gate is GateOutcome.PASS
