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
from core.assertions.confidence import Confidence
from core.assertions.state import AssertionState
from core.entities.context import Context
from core.entities.entity import Entity, EntityKind
from core.evidence.evidence import Evidence, EvidenceKind
from core.fusion.candidate_finder import EnhancedCandidateMatch
from core.fusion.meaning_aligner import MeaningAligner
from core.fusion.normalizer import DataNormalizer, NormalizedGraph
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin, Provenance
from sdk.domain_config import (
    DomainFusionConfig,
    EntityTypeConfig,
    MappingDirection,
    MeaningAlignmentConfig,
    MeaningMapping,
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


def test_multimap_preserves_multiple_mappings_for_same_concept() -> None:
    """R2.1, P1-13: Multimap preserves multiple mappings for the same source concept without overwriting."""
    mapping1 = MeaningMapping(
        source_concept="worksAt",
        target_concept="employedBy",
        direction=MappingDirection.EQUIVALENT,
        confidence=0.9,
    )
    mapping2 = MeaningMapping(
        source_concept="worksAt",
        target_concept="affiliatedWith",
        direction=MappingDirection.EQUIVALENT,
        confidence=0.8,
    )
    config = DomainFusionConfig(
        meaning_alignment=MeaningAlignmentConfig(
            relation_mappings=(mapping1, mapping2),
        ),
    )
    aligner = MeaningAligner(config)

    # Both mappings are preserved in multimap
    stored_mappings = aligner._rel_map[("worksat", "graph_a")]
    assert len(stored_mappings) == 2
    assert any(m.target_concept == "employedBy" for m in stored_mappings)
    assert any(m.target_concept == "affiliatedWith" for m in stored_mappings)

    # align_predicate selects highest confidence mapping
    canonical_pred, selected_mapping = aligner.align_predicate("worksAt", from_graph="graph_a")
    assert canonical_pred == "employedBy"
    assert selected_mapping is not None
    assert selected_mapping.confidence == 0.9


def test_symmetric_class_validation_matches_when_both_types_present() -> None:
    """R2.2, P1-13b: Symmetric class validation succeeds when both source and target types match."""
    mapping = MeaningMapping(
        source_concept="AntidiabeticAgent",
        target_concept="Drug",
        direction=MappingDirection.DIRECTED_A_TO_B,
    )
    config = DomainFusionConfig(
        meaning_alignment=MeaningAlignmentConfig(class_mappings=(mapping,)),
        entity_types=(
            EntityTypeConfig(name="AntidiabeticAgent", namespace_prefixes=("antidiabetic",)),
            EntityTypeConfig(name="Drug", namespace_prefixes=("drugs",)),
        ),
    )
    aligner = MeaningAligner(config)

    e1 = Entity(
        id=Identifier(namespace="EX", value="http://example.org/antidiabetic/Metformin"),
        kind=EntityKind.CONCEPT,
        label="Metformin",
    )
    e2 = Entity(
        id=Identifier(namespace="EX", value="http://example.org/drugs/Metformin_HCl"),
        kind=EntityKind.CONCEPT,
        label="Metformin HCl",
    )
    cand = EnhancedCandidateMatch(
        source_entity=e1,
        candidate_entity=e2,
        composite_score=0.92,
        primary_method="normalized_label",
    )

    norm_a = NormalizedGraph(graph_id="graph_a", entities={e1.id.value: e1})
    norm_b = NormalizedGraph(graph_id="graph_b", entities={e2.id.value: e2})

    result = aligner.align_candidates([cand], norm_a, norm_b)
    assert result.mappings_applied_count == 1
    assert len(result.mappings_applied_log) == 1
    assert "Class mapping: AntidiabeticAgent ↔ Drug" in result.mappings_applied_log[0]["mappings"]


def test_symmetric_class_validation_rejects_when_target_type_mismatch() -> None:
    """R2.2, P1-13b: Symmetric class validation rejects when candidate entity does not match target type."""
    mapping = MeaningMapping(
        source_concept="AntidiabeticAgent",
        target_concept="Drug",
        direction=MappingDirection.DIRECTED_A_TO_B,
    )
    config = DomainFusionConfig(
        meaning_alignment=MeaningAlignmentConfig(class_mappings=(mapping,)),
        entity_types=(
            EntityTypeConfig(name="AntidiabeticAgent", namespace_prefixes=("antidiabetic",)),
            EntityTypeConfig(name="Drug", namespace_prefixes=("drugs",)),
            EntityTypeConfig(name="Vehicle", namespace_prefixes=("vehicles",)),
        ),
    )
    aligner = MeaningAligner(config)

    e1 = Entity(
        id=Identifier(namespace="EX", value="http://example.org/antidiabetic/Metformin"),
        kind=EntityKind.CONCEPT,
        label="Metformin",
    )
    # Candidate entity is a Vehicle, NOT a Drug
    e2_mismatch = Entity(
        id=Identifier(namespace="EX", value="http://example.org/vehicles/Car"),
        kind=EntityKind.OBJECT,
        label="Delivery Car",
    )
    cand = EnhancedCandidateMatch(
        source_entity=e1,
        candidate_entity=e2_mismatch,
        composite_score=0.85,
        primary_method="normalized_label",
    )

    norm_a = NormalizedGraph(graph_id="graph_a", entities={e1.id.value: e1})
    norm_b = NormalizedGraph(graph_id="graph_b", entities={e2_mismatch.id.value: e2_mismatch})

    result = aligner.align_candidates([cand], norm_a, norm_b)
    # Mapping must NOT apply because target entity type does not match Drug
    assert result.mappings_applied_count == 0
    assert len(result.mappings_applied_log) == 0


def test_symmetric_class_validation_respects_directed_directionality() -> None:
    """R2.2, P1-13b: DIRECTED_A_TO_B mapping is not applied if reversed (B to A)."""
    mapping = MeaningMapping(
        source_concept="AntidiabeticAgent",
        target_concept="Drug",
        direction=MappingDirection.DIRECTED_A_TO_B,
    )
    config = DomainFusionConfig(
        meaning_alignment=MeaningAlignmentConfig(class_mappings=(mapping,)),
        entity_types=(
            EntityTypeConfig(name="AntidiabeticAgent", namespace_prefixes=("antidiabetic",)),
            EntityTypeConfig(name="Drug", namespace_prefixes=("drugs",)),
        ),
    )
    aligner = MeaningAligner(config)

    # Reversed: Source in Graph A is Drug, Candidate in Graph B is AntidiabeticAgent
    e_drug = Entity(
        id=Identifier(namespace="EX", value="http://example.org/drugs/Metformin_HCl"),
        kind=EntityKind.CONCEPT,
        label="Metformin HCl",
    )
    e_anti = Entity(
        id=Identifier(namespace="EX", value="http://example.org/antidiabetic/Metformin"),
        kind=EntityKind.CONCEPT,
        label="Metformin",
    )
    cand = EnhancedCandidateMatch(
        source_entity=e_drug,
        candidate_entity=e_anti,
        composite_score=0.90,
        primary_method="normalized_label",
    )

    norm_a = NormalizedGraph(graph_id="graph_a", entities={e_drug.id.value: e_drug})
    norm_b = NormalizedGraph(graph_id="graph_b", entities={e_anti.id.value: e_anti})

    result = aligner.align_candidates([cand], norm_a, norm_b)
    assert result.mappings_applied_count == 0
    assert len(result.mappings_applied_log) == 0


def test_aligned_assertions_deterministic_hash_id() -> None:
    """R2.3, P1-14: Aligned assertions generate deterministic, non-colliding SHA-256 hash IDs."""
    config = get_biomedical_preset()
    aligner = MeaningAligner(config)
    normalizer = DataNormalizer(config)

    assertion = _make_test_assertion("a1", "INS_Gene", "encodes", "Insulin_Protein")
    norm = normalizer.normalize_graph([assertion], "graph_a")
    aligned_list_1 = aligner.align_assertions(norm, "graph_a")
    aligned_list_2 = aligner.align_assertions(norm, "graph_a")

    assert len(aligned_list_1) == 1
    aligned_1 = aligned_list_1[0]
    aligned_2 = aligned_list_2[0]

    # Unique from original ID
    assert aligned_1.id != assertion.id
    assert aligned_1.id.namespace == "ASSERT"
    assert aligned_1.id.value.startswith("aligned_")

    # Deterministic: Identical inputs produce identical IDs
    assert aligned_1.id == aligned_2.id


def test_aligned_assertions_retain_all_metadata() -> None:
    """R2.3, P1-14: Aligned assertions retain context, confidence, evidence, and status_at_creation."""
    config = get_biomedical_preset()
    aligner = MeaningAligner(config)
    normalizer = DataNormalizer(config)

    ctx = Context(location="test_lab", conditions={"assay": "in_vitro"})
    conf = Confidence(score=0.96)
    evid = (
        Evidence(
            id=Identifier(namespace="EVID", value="ev1"),
            record_id=Identifier(namespace="REC", value="rec1"),
            kind=EvidenceKind.PRIMARY,
        ),
    )
    assertion = Assertion(
        id=Identifier(namespace="ASSERT", value="meta_test_1"),
        subject=Identifier(namespace="ENTITY", value="INS_Gene"),
        predicate="encodes",
        object=Identifier(namespace="ENTITY", value="Insulin_Protein"),
        context=ctx,
        confidence=conf,
        evidence=evid,
        provenance=Provenance(
            agent_id=Identifier(namespace="SYS", value="agent_curator"),
            activity_id=Identifier(namespace="SYS", value="act_align"),
            asserted_at=datetime.now(UTC),
        ),
        status_at_creation=AssertionState.VERIFIED,
    )

    norm = normalizer.normalize_graph([assertion], "graph_a")
    aligned_assertions = aligner.align_assertions(norm, "graph_a")

    assert len(aligned_assertions) == 1
    aligned = aligned_assertions[0]

    assert aligned.predicate == "producesProtein"
    assert aligned.context == ctx
    assert aligned.confidence == conf
    assert aligned.evidence == evid
    assert aligned.status_at_creation == AssertionState.VERIFIED


def test_aligned_assertions_cryptographic_lineage_provenance() -> None:
    """R2.3, P1-14: Aligned assertion provenance records DERIVED origin, input assertion refs, and derivation method."""
    config = get_biomedical_preset()
    aligner = MeaningAligner(config)
    normalizer = DataNormalizer(config)

    orig_assertion = _make_test_assertion("a_orig", "INS_Gene", "encodes", "Insulin_Protein")
    norm = normalizer.normalize_graph([orig_assertion], "graph_a")
    aligned_assertions = aligner.align_assertions(norm, "graph_a")

    aligned = aligned_assertions[0]
    prov = aligned.provenance

    assert prov.assertion_origin == AssertionOrigin.DERIVED
    assert prov.input_assertion_refs == (orig_assertion.id,)
    assert prov.derivation_method == "meaning_alignment"
    assert prov.agent_id == orig_assertion.provenance.agent_id
    assert prov.activity_id == orig_assertion.provenance.activity_id
    assert prov.asserted_at == orig_assertion.provenance.asserted_at


def test_aligned_literal_assertions_hash_id_and_lineage() -> None:
    """R2.3, P1-14: Literal attribute assertions receive hash IDs and derived provenance."""
    config = get_synthetic_preset()
    aligner = MeaningAligner(config)
    normalizer = DataNormalizer(config)

    lit_assertion = Assertion(
        id=Identifier(namespace="ASSERT", value="lit_raw"),
        subject=Identifier(namespace="ENTITY", value="Person_1"),
        predicate="fullName",
        object=Identifier(namespace="LITERAL", value="Jane_Doe"),
        provenance=Provenance(
            agent_id=Identifier(namespace="SYS", value="test_agent"),
            activity_id=Identifier(namespace="SYS", value="test_act"),
            asserted_at=datetime.now(UTC),
        ),
    )

    norm = normalizer.normalize_graph([lit_assertion], "graph_a")
    aligned_assertions = aligner.align_assertions(norm, "graph_a")

    assert len(aligned_assertions) == 1
    aligned = aligned_assertions[0]
    assert aligned.predicate == "name"
    assert aligned.id.value.startswith("aligned_")
    assert aligned.id != lit_assertion.id
    assert aligned.provenance.assertion_origin == AssertionOrigin.DERIVED
    assert aligned.provenance.input_assertion_refs == (lit_assertion.id,)
    assert aligned.provenance.derivation_method == "meaning_alignment"
