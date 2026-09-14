"""Validation extension contracts.

Validation mechanics (contexts, results, aggregation, release gates) live
in core. Domain-specific validation rules enter exclusively through the
``Validator`` contract; core never decides what valid content looks like
for a given domain.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.identifiers.identifier import Identifier
from core.validation.context import ValidationContext
from core.validation.result import ValidationResult


@runtime_checkable
class Validator(Protocol):
    """Extension contract for a validation step.

    Every validator — structural, logical, application, evidence, or
    projection — returns the same generic ``ValidationResult`` schema.
    """

    @property
    def name(self) -> str:
        """Stable identifier for the validator."""
        ...

    @property
    def version(self) -> str:
        """Version of the validator implementation."""
        ...

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        """Run the validation and return its results."""
        ...


@runtime_checkable
class StructuralValidator(Validator, Protocol):
    """Validates the structure of a target (shape, required fields, types)."""


@runtime_checkable
class LogicalValidator(Validator, Protocol):
    """Validates the logical consistency of a target (conflicts, invariants)."""


@runtime_checkable
class ApplicationValidator(Validator, Protocol):
    """Validates application-level constraints on a target (workflow, policy fit)."""


@runtime_checkable
class EvidenceValidator(Validator, Protocol):
    """Validates evidence backing a target (sufficiency, provenance, citation)."""


@runtime_checkable
class ProjectionValidator(Validator, Protocol):
    """Validates that projections stay consistent with the source of truth."""
