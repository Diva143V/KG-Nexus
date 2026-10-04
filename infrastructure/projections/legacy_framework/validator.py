"""ProjectionValidator: check a projection against its declared profile."""

from __future__ import annotations

from core.identifiers.identifier import Identifier
from core.validation.result import ValidationResult, ValidationSeverity, ValidationStatus
from infrastructure.projections.legacy_framework.content import ProjectionContent
from infrastructure.projections.legacy_framework.profile import (
    ProjectionProfile,
    UnsupportedBehavior,
)


class ProjectionValidator:
    """Validates that a projection's audit trails match its declared profile.

    The projection is valid when:

    * every dropped semantic was declared as dropped by the profile;
    * every unsupported semantic was declared as unsupported;
    * unsupported data followed the declared behavior (error/skip/flatten).
    """

    def validate(
        self,
        *,
        content: ProjectionContent,
        profile: ProjectionProfile,
        activity_id: Identifier,
    ) -> tuple[ValidationResult, ...]:
        """Return validation results for ``content`` against ``profile``."""
        results = [
            self._check_profile_name(content, profile, activity_id),
            self._check_dropped_declared(content, profile, activity_id),
            self._check_unsupported_declared(content, profile, activity_id),
            self._check_unsupported_behavior(content, profile, activity_id),
        ]
        return tuple(results)

    @staticmethod
    def _result(
        *,
        target: str,
        code: str,
        message: str,
        status: ValidationStatus,
        severity: ValidationSeverity,
        activity_id: Identifier,
    ) -> ValidationResult:
        return ValidationResult(
            validation_id=Identifier(
                namespace="projection-validation",
                value=f"{target}:{code}",
            ),
            validator="projection-validator",
            validator_version="1",
            target=target,
            severity=severity,
            code=code,
            message=message,
            status=status,
            activity_id=activity_id,
        )

    def _check_profile_name(
        self,
        content: ProjectionContent,
        profile: ProjectionProfile,
        activity_id: Identifier,
    ) -> ValidationResult:
        ok = content.profile == profile.name and content.profile_version == profile.version
        return self._result(
            target=content.projection_id.canonical,
            code="profile_mismatch",
            message="projection references the declared profile"
            if ok
            else "projection profile does not match the declared profile",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            severity=ValidationSeverity.ERROR if not ok else ValidationSeverity.INFO,
            activity_id=activity_id,
        )

    def _check_dropped_declared(
        self,
        content: ProjectionContent,
        profile: ProjectionProfile,
        activity_id: Identifier,
    ) -> ValidationResult:
        declared = set(profile.dropped_semantics)
        actual = set(content.dropped_semantics)
        undeclared = sorted(actual - declared)
        ok = not undeclared
        return self._result(
            target=content.projection_id.canonical,
            code="undeclared_drop",
            message="all dropped semantics were declared"
            if ok
            else f"undocumented drops: {undeclared}",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            severity=ValidationSeverity.ERROR if not ok else ValidationSeverity.INFO,
            activity_id=activity_id,
        )

    def _check_unsupported_declared(
        self,
        content: ProjectionContent,
        profile: ProjectionProfile,
        activity_id: Identifier,
    ) -> ValidationResult:
        declared = set(profile.unsupported_semantics)
        actual = set(content.unsupported_semantics)
        undeclared = sorted(actual - declared)
        ok = not undeclared
        return self._result(
            target=content.projection_id.canonical,
            code="undeclared_unsupported",
            message="all unsupported semantics were declared"
            if ok
            else f"undocumented unsupported: {undeclared}",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            severity=ValidationSeverity.ERROR if not ok else ValidationSeverity.INFO,
            activity_id=activity_id,
        )

    def _check_unsupported_behavior(
        self,
        content: ProjectionContent,
        profile: ProjectionProfile,
        activity_id: Identifier,
    ) -> ValidationResult:
        ok = True
        if profile.unsupported_behavior is UnsupportedBehavior.ERROR:
            ok = not content.unsupported_semantics
        return self._result(
            target=content.projection_id.canonical,
            code="unsupported_behavior",
            message="unsupported data followed the declared behavior"
            if ok
            else "content contains unsupported data under behavior=error",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            severity=ValidationSeverity.ERROR if not ok else ValidationSeverity.INFO,
            activity_id=activity_id,
        )
