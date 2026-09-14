"""Phase 12: Projection Framework tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.identifiers.identifier import Identifier
from core.projections import (
    ActiveProjectionError,
    FieldTransformation,
    InvalidProjectionTransitionError,
    ProjectedEdge,
    ProjectedNode,
    Projection,
    ProjectionBuilder,
    ProjectionContent,
    ProjectionError,
    ProjectionGate,
    ProjectionManager,
    ProjectionProfile,
    ProjectionReconciler,
    ProjectionStatus,
    ProjectionStatusResolver,
    ProjectionValidator,
    ReconciliationMethod,
    ReconciliationOutcome,
    TransformationKind,
    UndeclaredSemanticsError,
    UnsupportedBehavior,
    UnsupportedSemanticsError,
)
from core.rdf.graph import NamedGraph, RDFDataset
from core.rdf.terms import Triple, iri, string_literal
from core.validation.result import ValidationStatus
from infrastructure.projections.memory import MemoryProjectionBackend, conforms_to_backend
from tests.helpers import ident, utc

P_LABEL = "urn:label"
P_LINKED = "urn:linked"
P_DEPRECATED = "urn:deprecated"
P_OPAQUE = "urn:opaque"

DROPPED = ("urn:deprecated",)
UNSUPPORTED = ("urn:opaque",)


def profile(
    *,
    behavior: UnsupportedBehavior = UnsupportedBehavior.SKIP,
    reconciliation: ReconciliationMethod = ReconciliationMethod.REBUILD,
) -> ProjectionProfile:
    return ProjectionProfile(
        name="entity-graph",
        version="1",
        preserved_fields=(P_LABEL,),
        transformations=(
            FieldTransformation(
                name="linked",
                source=P_LINKED,
                target="linked",
                kind=TransformationKind.EDGE,
            ),
        ),
        dropped_semantics=DROPPED,
        unsupported_semantics=UNSUPPORTED,
        unsupported_behavior=behavior,
        reconciliation_method=reconciliation,
    )


def dataset() -> RDFDataset:
    return RDFDataset(
        graphs=(
            NamedGraph(
                name="urn:graph:test",
                triples=(
                    Triple(
                        subject=iri("urn:entity:e-1"),
                        predicate=iri(P_LABEL),
                        object=string_literal("Alpha"),
                    ),
                    Triple(
                        subject=iri("urn:entity:e-1"),
                        predicate=iri(P_LINKED),
                        object=iri("urn:entity:e-2"),
                    ),
                    Triple(
                        subject=iri("urn:entity:e-2"),
                        predicate=iri(P_LABEL),
                        object=string_literal("Beta"),
                    ),
                    Triple(
                        subject=iri("urn:entity:e-1"),
                        predicate=iri(P_DEPRECATED),
                        object=string_literal("yes"),
                    ),
                    Triple(
                        subject=iri("urn:entity:e-1"),
                        predicate=iri(P_OPAQUE),
                        object=string_literal("x"),
                    ),
                ),
            ),
        )
    )


def projection_id() -> Identifier:
    return ident("projection", "p-1")


def build(prof: ProjectionProfile | None = None) -> ProjectionContent:
    return ProjectionBuilder().build(
        projection_id=projection_id(),
        dataset=dataset(),
        profile=prof or profile(),
    )


class TestProjectionProfile:
    def test_declares_all_required_sections(self) -> None:
        p = profile()
        assert p.preserved_fields == (P_LABEL,)
        assert p.transformations[0].source == P_LINKED
        assert p.dropped_semantics == DROPPED
        assert p.unsupported_semantics == UNSUPPORTED
        assert p.reconciliation_method is ReconciliationMethod.REBUILD

    def test_default_reconciliation_is_rebuild(self) -> None:
        p = ProjectionProfile(name="x", version="1")
        assert p.reconciliation_method is ReconciliationMethod.REBUILD

    def test_profile_is_immutable(self) -> None:
        p = profile()
        with pytest.raises(ValidationError):
            p.preserved_fields = ()

    def test_rejects_overlapping_declarations(self) -> None:
        with pytest.raises(ValidationError):
            ProjectionProfile(
                name="x",
                version="1",
                preserved_fields=(P_LABEL,),
                dropped_semantics=(P_LABEL,),
            )


class TestProjectionBuilder:
    def test_preserved_field_becomes_node_property(self) -> None:
        content = build()
        node = next(node for node in content.nodes if node.key == "urn:entity:e-1")
        assert node.properties[P_LABEL] == "Alpha"

    def test_transformation_creates_edge(self) -> None:
        content = build()
        assert content.edges == (
            ProjectedEdge(source="urn:entity:e-1", type="linked", target="urn:entity:e-2"),
        )

    def test_nodes_include_all_subjects(self) -> None:
        content = build()
        keys = {node.key for node in content.nodes}
        assert keys == {"urn:entity:e-1", "urn:entity:e-2"}

    def test_dropped_semantics_are_audited_not_silent(self) -> None:
        content = build()
        assert content.dropped_semantics == DROPPED
        assert content.unsupported_semantics == UNSUPPORTED

    def test_deterministic_ordering(self) -> None:
        assert build().nodes == build().nodes
        assert build().digest == build().digest

    def test_undeclared_semantics_raise(self) -> None:
        prof = profile()
        data = RDFDataset(
            graphs=(
                NamedGraph(
                    name="urn:graph:test",
                    triples=(
                        Triple(
                            subject=iri("urn:entity:e-1"),
                            predicate=iri("urn:mystery"),
                            object=string_literal("x"),
                        ),
                    ),
                ),
            )
        )
        with pytest.raises(UndeclaredSemanticsError):
            ProjectionBuilder().build(projection_id=projection_id(), dataset=data, profile=prof)

    def test_unsupported_error_behavior_raises(self) -> None:
        prof = profile(behavior=UnsupportedBehavior.ERROR)
        with pytest.raises(UnsupportedSemanticsError):
            build(prof)

    def test_unsupported_skip_behavior_records(self) -> None:
        content = build()
        assert P_OPAQUE in content.unsupported_semantics

    def test_unsupported_flatten_behavior_records(self) -> None:
        prof = profile(behavior=UnsupportedBehavior.FLATTEN)
        content = build(prof)
        assert P_OPAQUE in content.unsupported_semantics
        assert content.nodes

    def test_property_transformation_kind(self) -> None:
        prof = ProjectionProfile(
            name="property-transform",
            version="1",
            transformations=(
                FieldTransformation(
                    name="label-renamed",
                    source=P_LABEL,
                    target="display_name",
                    kind=TransformationKind.PROPERTY,
                ),
            ),
            dropped_semantics=DROPPED + (P_LINKED,),
            unsupported_semantics=UNSUPPORTED,
            unsupported_behavior=UnsupportedBehavior.SKIP,
        )
        content = ProjectionBuilder().build(
            projection_id=projection_id(),
            dataset=dataset(),
            profile=prof,
        )
        node = next(node for node in content.nodes if node.key == "urn:entity:e-1")
        assert node.properties["display_name"] == "Alpha"
        assert P_LABEL not in node.properties

    def test_node_transformation_kind(self) -> None:
        prof = ProjectionProfile(
            name="node-transform",
            version="1",
            transformations=(
                FieldTransformation(
                    name="label-as-node",
                    source=P_LABEL,
                    target="labeled",
                    kind=TransformationKind.NODE,
                ),
            ),
            dropped_semantics=DROPPED + (P_LINKED,),
            unsupported_semantics=UNSUPPORTED,
            unsupported_behavior=UnsupportedBehavior.SKIP,
        )
        content = ProjectionBuilder().build(
            projection_id=projection_id(),
            dataset=dataset(),
            profile=prof,
        )
        kinds = {node.key: node.kind for node in content.nodes}
        assert kinds == {"Alpha": "labeled", "Beta": "labeled"}


class TestProjectionValidator:
    def test_valid_content_passes(self) -> None:
        content = build()
        results = ProjectionValidator().validate(
            content=content,
            profile=profile(),
            activity_id=ident("activity", "a-1"),
        )
        assert all(result.status is ValidationStatus.PASS for result in results)

    def test_undocumented_drop_fails(self) -> None:
        content = build().model_copy(update={"dropped_semantics": ("urn:new",)})
        results = ProjectionValidator().validate(
            content=content,
            profile=profile(),
            activity_id=ident("activity", "a-1"),
        )
        assert any(result.status is ValidationStatus.FAIL for result in results)

    def test_profile_mismatch_fails(self) -> None:
        content = build().model_copy(update={"profile": "other"})
        results = ProjectionValidator().validate(
            content=content,
            profile=profile(),
            activity_id=ident("activity", "a-1"),
        )
        assert any(result.status is ValidationStatus.FAIL for result in results)


class TestProjectionReconciler:
    def test_rebuild_reconciles(self) -> None:
        content = build()
        result = ProjectionReconciler().reconcile(
            projection_id=projection_id(),
            dataset=dataset(),
            content=content,
            profile=profile(),
        )
        assert result.reconciled
        assert result.outcome is ReconciliationOutcome.RECONCILED

    def test_rebuild_detects_drift(self) -> None:
        drifted = build().model_copy(update={"dropped_semantics": ()})
        result = ProjectionReconciler().reconcile(
            projection_id=projection_id(),
            dataset=dataset(),
            content=drifted,
            profile=profile(),
        )
        assert not result.reconciled
        assert result.outcome is ReconciliationOutcome.DRIFTED

    def test_digest_method(self) -> None:
        prof = profile(reconciliation=ReconciliationMethod.DIGEST)
        content = build(prof)
        result = ProjectionReconciler().reconcile(
            projection_id=projection_id(),
            dataset=dataset(),
            content=content,
            profile=prof,
        )
        assert result.reconciled

    def test_row_by_row_method(self) -> None:
        prof = profile(reconciliation=ReconciliationMethod.ROW_BY_ROW)
        content = build(prof)
        result = ProjectionReconciler().reconcile(
            projection_id=projection_id(),
            dataset=dataset(),
            content=content,
            profile=prof,
        )
        assert result.reconciled


class TestProjectionStatusResolver:
    def test_full_lifecycle_chain(self) -> None:
        resolver = ProjectionStatusResolver()
        assert resolver.can_transition(ProjectionStatus.BUILDING, ProjectionStatus.VALIDATING)
        assert resolver.can_transition(ProjectionStatus.VALIDATING, ProjectionStatus.RECONCILED)
        assert resolver.can_transition(ProjectionStatus.RECONCILED, ProjectionStatus.READY)
        assert resolver.can_transition(ProjectionStatus.READY, ProjectionStatus.ACTIVE)
        assert resolver.can_transition(
            ProjectionStatus.ACTIVE, ProjectionStatus.RETAINED_FOR_ROLLBACK
        )

    def test_retained_is_terminal(self) -> None:
        resolver = ProjectionStatusResolver()
        assert resolver.is_terminal(ProjectionStatus.RETAINED_FOR_ROLLBACK)

    def test_cannot_skip_states(self) -> None:
        resolver = ProjectionStatusResolver()
        assert not resolver.can_transition(ProjectionStatus.BUILDING, ProjectionStatus.RECONCILED)
        assert not resolver.can_transition(
            ProjectionStatus.READY, ProjectionStatus.RETAINED_FOR_ROLLBACK
        )

    def test_activate_requires_ready(self) -> None:
        resolver = ProjectionStatusResolver()
        assert resolver.can_activate(ProjectionStatus.READY)
        assert not resolver.can_activate(ProjectionStatus.RECONCILED)


class TestProjectionManager:
    def build_manager(self) -> tuple[ProjectionManager, Projection]:
        manager = ProjectionManager()
        projection = manager.create_projection(
            projection_id=projection_id(),
            name="entity-graph",
            profile=profile(),
            created_at=utc(2026, 1, 1),
        )
        return manager, projection

    def test_create_is_building(self) -> None:
        manager, projection = self.build_manager()
        assert projection.status is ProjectionStatus.BUILDING
        assert manager.get_projection(projection_id()) is projection

    def test_duplicate_projection_rejected(self) -> None:
        manager, _ = self.build_manager()
        with pytest.raises(ValueError, match="duplicate"):
            manager.create_projection(
                projection_id=projection_id(),
                name="x",
                profile=profile(),
            )

    def test_lifecycle_completes(self) -> None:
        manager, projection = self.build_manager()
        content = build()
        validating = manager.begin_validation(projection, content=content, at=utc(2026, 1, 2))
        assert validating.status is ProjectionStatus.VALIDATING
        assert validating.content == content

        reconciled = manager.complete_validation(
            validating,
            gate=ProjectionGate(validation=True, reconciliation=True),
            activity_id=ident("activity", "a-1"),
            at=utc(2026, 1, 3),
        )
        assert reconciled.status is ProjectionStatus.RECONCILED

        ready = manager.mark_ready(reconciled, at=utc(2026, 1, 4))
        assert ready.status is ProjectionStatus.READY

        active = manager.activate(ready, at=utc(2026, 1, 5))
        assert active.status is ProjectionStatus.ACTIVE
        assert active.activated_at == utc(2026, 1, 5)

        retained = manager.retain_for_rollback(active, at=utc(2026, 1, 6))
        assert retained.status is ProjectionStatus.RETAINED_FOR_ROLLBACK

    def test_validation_failure_blocks(self) -> None:
        manager, projection = self.build_manager()
        content = build()
        validating = manager.begin_validation(projection, content=content, at=utc(2026, 1, 2))
        with pytest.raises(ProjectionError):
            manager.complete_validation(
                validating,
                gate=ProjectionGate(validation=True, reconciliation=False),
                activity_id=ident("activity", "a-1"),
            )
        assert manager.get_projection(projection_id()).status is ProjectionStatus.VALIDATING

    def test_active_is_immutable(self) -> None:
        manager, projection = self.build_manager()
        content = build()
        validating = manager.begin_validation(projection, content=content, at=utc(2026, 1, 2))
        reconciled = manager.complete_validation(
            validating,
            gate=ProjectionGate(validation=True, reconciliation=True),
            activity_id=ident("activity", "a-1"),
            at=utc(2026, 1, 3),
        )
        ready = manager.mark_ready(reconciled, at=utc(2026, 1, 4))
        active = manager.activate(ready, at=utc(2026, 1, 5))
        with pytest.raises(ActiveProjectionError):
            manager.begin_validation(active, content=content)

    def test_invalid_transition_raises(self) -> None:
        manager, projection = self.build_manager()
        with pytest.raises(InvalidProjectionTransitionError):
            manager.activate(projection)

    def test_unknown_projection_raises(self) -> None:
        manager = ProjectionManager()
        unknown = Projection(
            id=ident("projection", "missing"),
            name="x",
            profile=profile(),
            created_at=utc(2026, 1, 1),
        )
        with pytest.raises(ProjectionError, match="unknown"):
            manager.begin_validation(unknown, content=build())


class TestProjectionBackend:
    def test_memory_backend_roundtrip(self) -> None:
        backend = MemoryProjectionBackend()
        content = build()
        backend.write(content)
        assert backend.read(projection_id().canonical) == content

    def test_memory_backend_delete(self) -> None:
        backend = MemoryProjectionBackend()
        backend.write(build())
        backend.delete(projection_id().canonical)
        assert backend.read(projection_id().canonical) is None

    def test_memory_backend_overwrites(self) -> None:
        backend = MemoryProjectionBackend()
        first = build()
        second = first.model_copy(update={"nodes": ()})
        backend.write(first)
        backend.write(second)
        assert backend.read(projection_id().canonical) == second

    def test_backend_conforms_to_protocol(self) -> None:
        assert conforms_to_backend(MemoryProjectionBackend())
        assert not conforms_to_backend(object())


def test_content_digest_is_metamorphic() -> None:
    first = build()
    second = first.model_copy(update={"edges": tuple(reversed(first.edges))})
    assert first.digest == second.digest


def test_node_and_edge_models_are_frozen() -> None:
    node = ProjectedNode(key="k", kind="n")
    with pytest.raises(ValidationError):
        node.key = "x"
    edge = ProjectedEdge(source="a", type="t", target="b")
    with pytest.raises(ValidationError):
        edge.type = "z"
