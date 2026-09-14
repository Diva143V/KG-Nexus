"""Aggregation of validation results into reports and release gates."""

from __future__ import annotations

from collections.abc import Sequence

from core.identifiers.identifier import Identifier
from core.validation.context import ValidationContext
from core.validation.report import GateOutcome, ValidationReport
from core.validation.result import ValidationResult, ValidationSeverity, ValidationStatus
from sdk.validation import Validator


class ValidationAggregator:
    """Combines validator results into a release-gated report.

    The aggregator is deterministic: results are ordered by canonical
    validation id, and the release gate follows fixed severity rules.
    """

    def aggregate(self, results: Sequence[ValidationResult]) -> ValidationReport:
        """Aggregate results for a single target into an immutable report."""
        ordered = tuple(sorted(results, key=lambda result: result.validation_id.canonical))
        if not ordered:
            raise ValueError("cannot aggregate an empty result set")
        targets = {result.target for result in ordered}
        if len(targets) != 1:
            raise ValueError(f"results reference multiple targets: {sorted(targets)}")
        gate = self._gate(ordered)
        return ValidationReport(target=ordered[0].target, results=ordered, gate=gate)

    def run(
        self,
        *,
        validators: Sequence[Validator],
        context: ValidationContext,
        activity_id: Identifier,
    ) -> ValidationReport:
        """Run validators over a context and aggregate their results.

        A validator that raises produces an ERROR result instead of
        aborting the run.
        """
        results: list[ValidationResult] = []
        for validator in validators:
            try:
                results.extend(validator.validate(context=context, activity_id=activity_id))
            except Exception as exc:
                results.append(
                    ValidationResult(
                        validation_id=Identifier(
                            namespace="validation",
                            value=f"{context.target}:{validator.name}",
                        ),
                        validator=validator.name,
                        validator_version=validator.version,
                        target=context.target,
                        severity=ValidationSeverity.ERROR,
                        code="validator_error",
                        message=str(exc),
                        status=ValidationStatus.ERROR,
                        activity_id=activity_id,
                    )
                )
        if not results:
            raise ValueError("validators produced no results")
        return self.aggregate(results)

    @staticmethod
    def _gate(results: tuple[ValidationResult, ...]) -> GateOutcome:
        if any(
            result.status is ValidationStatus.FAIL and result.severity is ValidationSeverity.BLOCKER
            for result in results
        ):
            return GateOutcome.BLOCKED
        if any(
            result.status is ValidationStatus.FAIL and result.severity is ValidationSeverity.ERROR
            for result in results
        ):
            return GateOutcome.REVIEW
        if any(result.status is ValidationStatus.ERROR for result in results):
            return GateOutcome.REVIEW
        return GateOutcome.PASS
