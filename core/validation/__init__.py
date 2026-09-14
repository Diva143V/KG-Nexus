"""Generic validation framework: results, aggregation, release gates."""

from __future__ import annotations

from core.validation.aggregator import ValidationAggregator
from core.validation.context import ValidationContext
from core.validation.report import GateOutcome, ValidationReport
from core.validation.result import ValidationResult, ValidationSeverity, ValidationStatus

__all__ = [
    "GateOutcome",
    "ValidationAggregator",
    "ValidationContext",
    "ValidationReport",
    "ValidationResult",
    "ValidationSeverity",
    "ValidationStatus",
]
