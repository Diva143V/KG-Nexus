"""Phase 9: Core release lifecycle tests."""

from __future__ import annotations

from itertools import pairwise

import pytest
from pydantic import ValidationError

from core.releases.errors import (
    InvalidReleaseTransitionError,
    PublishedReleaseError,
    UnknownReleaseError,
)
from core.releases.manager import ReleaseManager
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release, ReleaseGate, ReleaseTransition
from core.releases.resolver import ReleaseStatusResolver
from core.releases.status import ReleaseStatus
from tests.helpers import ident, utc

LOCK = LockfileSet(
    ontology=ident("lockfile", "ontology-1.0"),
    runtime=ident("lockfile", "runtime-1.0"),
    model=ident("lockfile", "model-1.0"),
    reasoner=ident("lockfile", "reasoner-1.0"),
    projection=ident("lockfile", "projection-1.0"),
)

RELEASE_ID = ident("release", "kg-2026.1")


def manifest() -> ReleaseManifest:
    return ReleaseManifest(
        source_artifacts=(ident("artifact", "a-1"),),
        assertions=(ident("assertion", "a-1"),),
        policies=(ident("policy", "p-1"),),
        plugins=(ident("plugin", "plug-1"),),
        lockfiles=LOCK,
    )


def passing_gate() -> ReleaseGate:
    return ReleaseGate(
        structural=True,
        logical=True,
        application=True,
        evidence=True,
        projection=True,
        reconciliation=True,
    )


def build_manager() -> ReleaseManager:
    return ReleaseManager()


def create(manager: ReleaseManager) -> Release:
    return manager.create_release(
        release_id=RELEASE_ID,
        version="2026.1",
        manifest=manifest(),
        created_at=utc(2026, 1, 1),
    )


class TestReleaseManifest:
    def test_manifest_references_all_required_components(self) -> None:
        m = manifest()
        assert m.source_artifacts == (ident("artifact", "a-1"),)
        assert m.assertions == (ident("assertion", "a-1"),)
        assert m.policies == (ident("policy", "p-1"),)
        assert m.plugins == (ident("plugin", "plug-1"),)
        assert m.lockfiles.ontology == ident("lockfile", "ontology-1.0")
        assert m.lockfiles.runtime == ident("lockfile", "runtime-1.0")
        assert m.lockfiles.model == ident("lockfile", "model-1.0")
        assert m.lockfiles.reasoner == ident("lockfile", "reasoner-1.0")
        assert m.lockfiles.projection == ident("lockfile", "projection-1.0")

    def test_model_lockfile_is_optional(self) -> None:
        m = manifest().model_copy(update={"lockfiles": LOCK.model_copy(update={"model": None})})
        assert m.lockfiles.model is None

    def test_manifest_is_immutable(self) -> None:
        with pytest.raises(ValidationError):
            manifest().policies = ()

    def test_manifest_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ReleaseManifest.model_validate(
                {
                    "source_artifacts": [{"namespace": "artifact", "value": "a"}],
                    "assertions": [{"namespace": "assertion", "value": "a"}],
                    "policies": [{"namespace": "policy", "value": "p"}],
                    "plugins": [{"namespace": "plugin", "value": "plug"}],
                    "lockfiles": LOCK.model_dump(mode="json"),
                    "extra": 1,
                }
            )


class TestRelease:
    def test_new_release_is_candidate(self) -> None:
        release = create(build_manager())
        assert release.status is ReleaseStatus.CANDIDATE
        assert not release.is_published
        assert not release.is_quarantined
        assert release.transitions == ()
        assert release.gate is None

    def test_release_is_immutable(self) -> None:
        release = create(build_manager())
        with pytest.raises(ValidationError):
            release.status = ReleaseStatus.APPROVED


class TestReleaseStatusResolver:
    def test_transition_chain(self) -> None:
        resolver = ReleaseStatusResolver()
        chain = [
            ReleaseStatus.CANDIDATE,
            ReleaseStatus.VALIDATING,
            ReleaseStatus.VALIDATED,
            ReleaseStatus.PROJECTED,
            ReleaseStatus.RECONCILED,
            ReleaseStatus.APPROVED,
            ReleaseStatus.PUBLISHED,
        ]
        for current, nxt in pairwise(chain):
            assert resolver.can_transition(current, nxt), f"{current} -> {nxt}"

    def test_quarantine_reachable_from_all_non_terminal(self) -> None:
        resolver = ReleaseStatusResolver()
        for status in ReleaseStatus:
            if resolver.is_terminal(status):
                continue
            assert resolver.can_transition(status, ReleaseStatus.QUARANTINED)

    def test_published_is_terminal(self) -> None:
        resolver = ReleaseStatusResolver()
        assert resolver.is_terminal(ReleaseStatus.PUBLISHED)
        assert not resolver.can_transition(ReleaseStatus.PUBLISHED, ReleaseStatus.QUARANTINED)
        assert not resolver.can_transition(ReleaseStatus.PUBLISHED, ReleaseStatus.APPROVED)

    def test_quarantined_is_terminal(self) -> None:
        resolver = ReleaseStatusResolver()
        assert resolver.is_terminal(ReleaseStatus.QUARANTINED)

    def test_can_approve_requires_reconciled(self) -> None:
        resolver = ReleaseStatusResolver()
        assert resolver.can_approve(ReleaseStatus.RECONCILED)
        assert not resolver.can_approve(ReleaseStatus.VALIDATED)
        assert not resolver.can_approve(ReleaseStatus.APPROVED)

    def test_can_publish_requires_approved(self) -> None:
        resolver = ReleaseStatusResolver()
        assert resolver.can_publish(ReleaseStatus.APPROVED)
        assert not resolver.can_publish(ReleaseStatus.RECONCILED)
        assert not resolver.can_publish(ReleaseStatus.PUBLISHED)

    def test_skipping_states_is_rejected(self) -> None:
        resolver = ReleaseStatusResolver()
        assert not resolver.can_transition(ReleaseStatus.CANDIDATE, ReleaseStatus.APPROVED)
        assert not resolver.can_transition(ReleaseStatus.CANDIDATE, ReleaseStatus.PUBLISHED)
        assert not resolver.can_transition(ReleaseStatus.VALIDATING, ReleaseStatus.RECONCILED)
        assert not resolver.can_transition(ReleaseStatus.APPROVED, ReleaseStatus.RECONCILED)


class TestReleaseGate:
    def test_gate_passes_when_every_check_passes(self) -> None:
        assert passing_gate().passed

    def test_gate_blocks_when_any_check_fails(self) -> None:
        for field in (
            "structural",
            "logical",
            "application",
            "evidence",
            "projection",
            "reconciliation",
        ):
            gate = passing_gate().model_copy(update={field: False})
            assert not gate.passed, field

    def test_gate_defaults_to_false(self) -> None:
        assert not ReleaseGate().passed

    def test_gate_is_immutable(self) -> None:
        with pytest.raises(ValidationError):
            passing_gate().structural = False


class TestHappyPath:
    def test_full_lifecycle_to_published(self) -> None:
        manager = build_manager()
        release = create(manager)
        assert release.status is ReleaseStatus.CANDIDATE

        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        assert release.status is ReleaseStatus.VALIDATING

        release = manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        assert release.status is ReleaseStatus.VALIDATED
        assert release.gate is not None
        assert release.gate.passed

        release = manager.project(release, at=utc(2026, 1, 4))
        assert release.status is ReleaseStatus.PROJECTED

        release = manager.reconcile(release, gate=passing_gate(), at=utc(2026, 1, 5))
        assert release.status is ReleaseStatus.RECONCILED

        release = manager.approve(release, gate=passing_gate(), at=utc(2026, 1, 6))
        assert release.status is ReleaseStatus.APPROVED

        release = manager.publish(release, at=utc(2026, 1, 7))
        assert release.status is ReleaseStatus.PUBLISHED
        assert release.is_published
        assert release.published_at == utc(2026, 1, 7)

    def test_transitions_are_recorded(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        release = manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        statuses = [t.to_status for t in release.transitions]
        assert statuses == [ReleaseStatus.VALIDATING, ReleaseStatus.VALIDATED]
        assert release.transitions[0].from_status is ReleaseStatus.CANDIDATE
        assert release.transitions[0].reason == "validation started"

    def test_manager_returns_latest_instance(self) -> None:
        manager = build_manager()
        release = create(manager)
        updated = manager.begin_validation(release, at=utc(2026, 1, 2))
        assert manager.get_release(RELEASE_ID) is updated
        assert list(manager.iter_releases()) == [updated]


class TestValidationGate:
    def test_failed_validation_quarantines(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        gate = passing_gate().model_copy(update={"structural": False})
        release = manager.complete_validation(release, gate=gate, at=utc(2026, 1, 3))
        assert release.status is ReleaseStatus.QUARANTINED
        assert release.is_quarantined
        assert release.quarantine_reasons == ("validation failed",)

    def test_validation_failure_is_auditable(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        gate = passing_gate().model_copy(update={"evidence": False})
        release = manager.complete_validation(release, gate=gate, at=utc(2026, 1, 3))
        assert release.transitions[-1].to_status is ReleaseStatus.QUARANTINED


class TestReconciliationGate:
    def test_failed_reconciliation_quarantines(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        release = manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        release = manager.project(release, at=utc(2026, 1, 4))
        gate = passing_gate().model_copy(update={"reconciliation": False})
        release = manager.reconcile(release, gate=gate, at=utc(2026, 1, 5))
        assert release.status is ReleaseStatus.QUARANTINED
        assert release.quarantine_reasons == ("reconciliation failed",)


class TestApprovalGate:
    def _reconciled(self, manager: ReleaseManager) -> Release:
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        release = manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        release = manager.project(release, at=utc(2026, 1, 4))
        return manager.reconcile(release, gate=passing_gate(), at=utc(2026, 1, 5))

    def test_approval_requires_full_gate(self) -> None:
        failing_gates = [
            passing_gate().model_copy(update={field: False})
            for field in (
                "structural",
                "logical",
                "application",
                "evidence",
                "projection",
                "reconciliation",
            )
        ]
        for gate in failing_gates:
            manager = build_manager()
            release = self._reconciled(manager)
            release = manager.approve(release, gate=gate, at=utc(2026, 1, 6))
            assert release.status is ReleaseStatus.QUARANTINED, gate
            assert release.quarantine_reasons == ("release gate failed",)

    def test_approval_after_clean_validation(self) -> None:
        manager = build_manager()
        release = self._reconciled(manager)
        release = manager.approve(release, gate=passing_gate(), at=utc(2026, 1, 6))
        assert release.status is ReleaseStatus.APPROVED

    def test_cannot_approve_before_reconciled(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        release = manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        with pytest.raises(InvalidReleaseTransitionError):
            manager.approve(release, gate=passing_gate(), at=utc(2026, 1, 4))


class TestPublishing:
    def test_cannot_publish_unless_approved(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        release = manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        release = manager.project(release, at=utc(2026, 1, 4))
        release = manager.reconcile(release, gate=passing_gate(), at=utc(2026, 1, 5))
        with pytest.raises(InvalidReleaseTransitionError):
            manager.publish(release, at=utc(2026, 1, 6))

    def test_published_release_is_immutable(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        release = manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        release = manager.project(release, at=utc(2026, 1, 4))
        release = manager.reconcile(release, gate=passing_gate(), at=utc(2026, 1, 5))
        release = manager.approve(release, gate=passing_gate(), at=utc(2026, 1, 6))
        release = manager.publish(release, at=utc(2026, 1, 7))
        assert release.is_published
        with pytest.raises(PublishedReleaseError):
            manager.quarantine(release, at=utc(2026, 1, 8))
        with pytest.raises(PublishedReleaseError):
            manager.approve(release, gate=passing_gate(), at=utc(2026, 1, 8))


class TestManagerGuards:
    def test_duplicate_release_id_rejected(self) -> None:
        manager = build_manager()
        create(manager)
        with pytest.raises(ValueError, match="duplicate release"):
            create(manager)

    def test_unknown_release_rejected(self) -> None:
        manager = build_manager()
        orphan = Release(
            id=ident("release", "kg-unknown"),
            version="1.0",
            status=ReleaseStatus.CANDIDATE,
            manifest=manifest(),
            created_at=utc(2026, 1, 1),
        )
        with pytest.raises(UnknownReleaseError):
            manager.begin_validation(orphan, at=utc(2026, 1, 2))

    def test_stale_release_instance_rejected(self) -> None:
        manager = build_manager()
        release = create(manager)
        updated = manager.begin_validation(release, at=utc(2026, 1, 2))
        with pytest.raises(UnknownReleaseError):
            manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        assert manager.get_release(RELEASE_ID) is updated

    def test_skipped_state_transition_rejected(self) -> None:
        manager = build_manager()
        release = create(manager)
        with pytest.raises(InvalidReleaseTransitionError):
            manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 2))

    def test_quarantined_release_cannot_recover(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        gate = passing_gate().model_copy(update={"structural": False})
        release = manager.complete_validation(release, gate=gate, at=utc(2026, 1, 3))
        assert release.is_quarantined
        with pytest.raises(InvalidReleaseTransitionError):
            manager.begin_validation(release, at=utc(2026, 1, 4))


class TestAudit:
    def test_quarantine_reasons_recorded(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.quarantine(release, at=utc(2026, 1, 2), reasons=("policy error",))
        assert release.quarantine_reasons == ("policy error",)
        assert release.transitions[-1].to_status is ReleaseStatus.QUARANTINED

    def test_gate_is_recorded_on_approval(self) -> None:
        manager = build_manager()
        release = create(manager)
        release = manager.begin_validation(release, at=utc(2026, 1, 2))
        release = manager.complete_validation(release, gate=passing_gate(), at=utc(2026, 1, 3))
        release = manager.project(release, at=utc(2026, 1, 4))
        release = manager.reconcile(release, gate=passing_gate(), at=utc(2026, 1, 5))
        release = manager.approve(release, gate=passing_gate(), at=utc(2026, 1, 6))
        assert release.gate is not None
        assert release.gate.passed
        assert release.transitions[-1].reason == "release gate passed"


class TestTypes:
    def test_release_transition_type(self) -> None:
        transition = ReleaseTransition(
            from_status=ReleaseStatus.CANDIDATE,
            to_status=ReleaseStatus.VALIDATING,
            at=utc(2026, 1, 2),
        )
        assert transition.from_status is ReleaseStatus.CANDIDATE
        assert transition.to_status is ReleaseStatus.VALIDATING
        assert transition.reason == ""
