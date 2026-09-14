"""Phase 8: Validation Framework tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.identifiers.identifier import Identifier
from core.validation.aggregator import ValidationAggregator
from core.validation.context import ValidationContext
from core.validation.report import GateOutcome
from core.validation.result import ValidationResult, ValidationSeverity, ValidationStatus
from sdk.validation import (
    ApplicationValidator,
    EvidenceValidator,
    LogicalValidator,
    ProjectionValidator,
    StructuralValidator,
    Validator,
)
from tests.helpers import ident

ACTIVITY = ident("activity", "phase8-run-1")


def build(
    code: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.INFO,
    status: ValidationStatus = ValidationStatus.PASS,
    target: str = "assertion:a-1",
) -> ValidationResult:
    return ValidationResult(
        validation_id=ident("validation", f"{target}:{code}"),
        validator="test-validator",
        validator_version="1.0.0",
        target=target,
        severity=severity,
        code=code,
        message=f"result {code}",
        status=status,
        activity_id=ACTIVITY,
    )


def build_pass(target: str = "assertion:a-1") -> ValidationResult:
    return build("ok", target=target)


class PassValidator:
    """Fake validator that always passes."""

    name = "pass-check"
    version = "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        return (
            ValidationResult(
                validation_id=ident("validation", f"{context.target}:ok"),
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.INFO,
                code="ok",
                message="passed",
                status=ValidationStatus.PASS,
                activity_id=activity_id,
            ),
        )


class BlockingValidator:
    """Fake validator that reports a blocker."""

    name = "blocking-check"
    version = "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        return (
            ValidationResult(
                validation_id=ident("validation", f"{context.target}:blocker"),
                validator=self.name,
                validator_version=self.version,
                target=context.target,
                severity=ValidationSeverity.BLOCKER,
                code="blocker",
                message="blocked",
                status=ValidationStatus.FAIL,
                activity_id=activity_id,
            ),
        )


class ExplodingValidator:
    """Fake validator that raises at runtime."""

    name = "exploding-check"
    version = "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        del context, activity_id
        raise RuntimeError("boom")


class EmptyValidator:
    """Fake validator that returns no results."""

    name = "empty-check"
    version = "1.0.0"

    def validate(
        self,
        *,
        context: ValidationContext,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        del context, activity_id
        return ()


def make_context() -> ValidationContext:
    return ValidationContext(target="assertion:a-1", data={"confidence": 0.9})


class TestSeverityAndStatus:
    def test_severity_values(self) -> None:
        assert [s.value for s in ValidationSeverity] == ["info", "warning", "error", "blocker"]

    def test_status_values(self) -> None:
        assert [s.value for s in ValidationStatus] == ["pass", "fail", "skipped", "error"]

    def test_severity_is_distinct_from_policy_severity(self) -> None:
        from core.policies.policy import PolicySeverity

        assert [s.value for s in ValidationSeverity] != [s.value for s in PolicySeverity]


class TestValidationResult:
    def test_result_fields(self) -> None:
        result = build("ok")
        assert result.validation_id == ident("validation", "assertion:a-1:ok")
        assert result.validator == "test-validator"
        assert result.validator_version == "1.0.0"
        assert result.target == "assertion:a-1"
        assert result.severity is ValidationSeverity.INFO
        assert result.code == "ok"
        assert result.message == "result ok"
        assert result.status is ValidationStatus.PASS
        assert result.activity_id == ACTIVITY

    def test_result_is_immutable(self) -> None:
        result = build("ok")
        with pytest.raises(ValidationError):
            result.message = "changed"

    def test_result_requires_all_fields(self) -> None:
        with pytest.raises(ValidationError):
            ValidationResult(  # type: ignore[call-arg]
                validator="test-validator",
                validator_version="1.0.0",
                target="t",
                severity=ValidationSeverity.INFO,
                code="c",
                message="m",
                status=ValidationStatus.PASS,
                activity_id=ACTIVITY,
            )

    def test_result_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ValidationResult.model_validate(
                {
                    "validation_id": {"namespace": "validation", "value": "x"},
                    "validator": "v",
                    "validator_version": "1.0.0",
                    "target": "t",
                    "severity": "info",
                    "code": "c",
                    "message": "m",
                    "status": "pass",
                    "activity_id": {"namespace": "activity", "value": "a"},
                    "extra": 1,
                }
            )


class TestValidationContext:
    def test_context_fields(self) -> None:
        context = make_context()
        assert context.target == "assertion:a-1"
        assert context.data == {"confidence": 0.9}
        assert context.evidence == ()

    def test_context_is_immutable(self) -> None:
        with pytest.raises(ValidationError):
            make_context().data = {}


class TestValidatorInterfaces:
    def test_validator_protocol_is_runtime_checkable(self) -> None:
        assert isinstance(PassValidator(), Validator)
        assert not isinstance(object(), Validator)

    def test_structural_interface(self) -> None:
        assert isinstance(PassValidator(), StructuralValidator)

    def test_logical_interface(self) -> None:
        assert isinstance(PassValidator(), LogicalValidator)

    def test_application_interface(self) -> None:
        assert isinstance(PassValidator(), ApplicationValidator)

    def test_evidence_interface(self) -> None:
        assert isinstance(PassValidator(), EvidenceValidator)

    def test_projection_interface(self) -> None:
        assert isinstance(PassValidator(), ProjectionValidator)


class TestAggregator:
    def test_aggregate_sorts_by_validation_id(self) -> None:
        report = ValidationAggregator().aggregate([build("b"), build("a")])
        assert [r.code for r in report.results] == ["a", "b"]

    def test_aggregate_requires_single_target(self) -> None:
        with pytest.raises(ValueError, match="multiple targets"):
            ValidationAggregator().aggregate([build("a"), build("b", target="assertion:a-2")])

    def test_aggregate_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty result set"):
            ValidationAggregator().aggregate([])

    def test_aggregate_is_deterministic(self) -> None:
        aggregator = ValidationAggregator()
        results = [build("b"), build("a")]
        assert aggregator.aggregate(results) == aggregator.aggregate(list(reversed(results)))

    def test_report_is_immutable(self) -> None:
        report = ValidationAggregator().aggregate([build("a")])
        with pytest.raises(ValidationError):
            report.gate = GateOutcome.BLOCKED


class TestReleaseGate:
    def test_all_pass_passes_gate(self) -> None:
        report = ValidationAggregator().aggregate([build_pass()])
        assert report.gate is GateOutcome.PASS
        assert report.passed

    def test_warning_does_not_block(self) -> None:
        report = ValidationAggregator().aggregate(
            [
                build_pass(),
                build(
                    "w",
                    severity=ValidationSeverity.WARNING,
                    status=ValidationStatus.FAIL,
                ),
            ]
        )
        assert report.gate is GateOutcome.PASS
        assert len(report.warnings) == 1

    def test_error_requires_review(self) -> None:
        report = ValidationAggregator().aggregate(
            [
                build_pass(),
                build(
                    "e",
                    severity=ValidationSeverity.ERROR,
                    status=ValidationStatus.FAIL,
                ),
            ]
        )
        assert report.gate is GateOutcome.REVIEW
        assert len(report.errors) == 1

    def test_blocker_blocks_release(self) -> None:
        report = ValidationAggregator().aggregate(
            [
                build_pass(),
                build(
                    "x",
                    severity=ValidationSeverity.BLOCKER,
                    status=ValidationStatus.FAIL,
                ),
            ]
        )
        assert report.gate is GateOutcome.BLOCKED
        assert len(report.blockers) == 1
        assert not report.passed

    def test_blocker_dominates_error(self) -> None:
        report = ValidationAggregator().aggregate(
            [
                build("x", severity=ValidationSeverity.BLOCKER, status=ValidationStatus.FAIL),
                build("e", severity=ValidationSeverity.ERROR, status=ValidationStatus.FAIL),
            ]
        )
        assert report.gate is GateOutcome.BLOCKED


class TestRun:
    def test_run_aggregates_multiple_validators(self) -> None:
        report = ValidationAggregator().run(
            validators=[PassValidator(), PassValidator()],
            context=make_context(),
            activity_id=ACTIVITY,
        )
        assert report.target == "assertion:a-1"
        assert len(report.results) == 2
        assert report.gate is GateOutcome.PASS

    def test_run_catches_validator_exceptions(self) -> None:
        report = ValidationAggregator().run(
            validators=[ExplodingValidator()],
            context=make_context(),
            activity_id=ACTIVITY,
        )
        assert report.gate is GateOutcome.REVIEW
        assert len(report.results) == 1
        assert report.results[0].status is ValidationStatus.ERROR
        assert report.results[0].severity is ValidationSeverity.ERROR
        assert report.results[0].code == "validator_error"

    def test_run_requires_results(self) -> None:
        with pytest.raises(ValueError, match="no results"):
            ValidationAggregator().run(
                validators=[EmptyValidator()],
                context=make_context(),
                activity_id=ACTIVITY,
            )

    def test_run_propagates_blocker(self) -> None:
        report = ValidationAggregator().run(
            validators=[PassValidator(), BlockingValidator()],
            context=make_context(),
            activity_id=ACTIVITY,
        )
        assert report.gate is GateOutcome.BLOCKED
        assert report.blockers[0].validator == "blocking-check"
