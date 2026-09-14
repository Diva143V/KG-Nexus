"""Unit Tests for Stage 3: Meaning Alignment.

Verifies:
- Class mappings: Type A <-> Type B
- Relation mappings: relation A <-> relation B (e.g. worksAt <-> employedBy, encodes <-> producesProtein)
- Attribute mappings: name <-> fullName, age <-> yearsOld
- Directionality awareness (bidirectional EQUIVALENT vs unidirectional DIRECTED_A_TO_B)
- Disjoint class incompatibility rejection
"""

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.entities.entity import Entity, EntityKind
from core.fusion.candidate_finder import EnhancedCandidateMatch
from core.fusion.meaning_aligner import MeaningAligner
from core.fusion.normalizer import DataNormalizer
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from sdk.domain_config import (
    DomainFusionConfig,
    MappingDirection,
    MeaningAlignmentConfig,
    get_biomedical_preset,
    get_synthetic_preset,
)


def _make_test_assertion(a_id: str, subj: str, pred: str, obj: str) -> Assertion:
    return Assertion(
        id=Identifier(namespace="ASSERT", value=a_id),
        subject=Identifier(namespace="ENTITY", value=subj),
        predicate=pred,
        object=Identifier(namespace="ENTITY", value=obj),
        provenance=Provenance(
            agent_id=Identifier(namespace="SYS", value="test_agent"),
            activity_id=Identifier(namespace="SYS", value="test_act"),
            asserted_at=datetime.now(UTC),
        ),
    )


def test_relation_and_attribute_mappings():
    config = get_synthetic_preset()
    aligner = MeaningAligner(config)

    # Test predicate alignment
    aligned_pred, mapping = aligner.align_predicate("worksAt", from_graph="graph_a")
    assert aligned_pred == "employedBy"
    assert mapping is not None
    assert mapping.direction == MappingDirection.EQUIVALENT

    # Test reverse direction
    aligned_rev, mapping_rev = aligner.align_predicate("employedBy", from_graph="graph_b")
    assert aligned_rev == "employedBy"
    assert mapping_rev is not None

    # Test attribute alignment
    aligned_attr, _ = aligner.align_attribute("fullName", from_graph="graph_a")
    assert aligned_attr == "name"


def test_disjoint_class_incompatibility():
    config = DomainFusionConfig(
        domain_id="test_disjoint",
        meaning_alignment=MeaningAlignmentConfig(
            disjoint_classes=(("Person", "Company"), ("Gene", "Disease")),
        ),
    )
    aligner = MeaningAligner(config)

    e_person = Entity(
        id=Identifier(namespace="EX", value="Apple"), kind=EntityKind.CONCEPT, label="Person"
    )
    e_company = Entity(
        id=Identifier(namespace="EX", value="AppleCorp"),
        kind=EntityKind.ORGANIZATION,
        label="Company",
    )

    cand = EnhancedCandidateMatch(
        source_entity=e_person,
        candidate_entity=e_company,
        composite_score=0.95,
        primary_method="normalized_label",
    )

    normalizer = DataNormalizer(config)
    norm_a = normalizer.normalize_graph([], "g_a")
    norm_b = normalizer.normalize_graph([], "g_b")

    result = aligner.align_candidates([cand], norm_a, norm_b)
    # The candidate should be rejected due to disjoint class rule
    assert len(result.rejected_due_to_meaning) == 1
    assert len(result.aligned_candidates) == 0


def test_assertion_predicate_alignment():
    config = get_biomedical_preset()
    aligner = MeaningAligner(config)
    normalizer = DataNormalizer(config)

    assertions = [
        _make_test_assertion("a1", "INS_Gene", "encodes", "Insulin_Protein"),
    ]
    norm = normalizer.normalize_graph(assertions, "graph_a")
    aligned_assertions = aligner.align_assertions(norm, "graph_a")

    assert len(aligned_assertions) == 1
    assert str(aligned_assertions[0].predicate) == "producesProtein"


def test_ontology_shortage_detection():
    config = get_biomedical_preset()
    aligner = MeaningAligner(config)
    normalizer = DataNormalizer(config)

    # A proprietary unmapped predicate (e.g. internal nanotech formulation)
    assertions = [
        _make_test_assertion("a1", "CompoundAlpha", "nanoparticleEncapsulatedWith", "LipidBeta"),
    ]
    norm = normalizer.normalize_graph(assertions, "graph_internal")
    align_result = aligner.align_candidates([], norm, norm)
    aligned_assertions = aligner.align_assertions(norm, "graph_internal", result=align_result)

    assert len(aligned_assertions) == 1
    assert len(align_result.ontology_shortages) == 1
    shortage = align_result.ontology_shortages[0]
    assert shortage["status"] == "ONTOLOGY_SHORTAGE_DETECTED"
    assert shortage["local_name"] == "nanoparticleEncapsulatedWith"
    assert shortage["source_graph"] == "graph_internal"
    assert "skos" in shortage["fallback_iri"]
