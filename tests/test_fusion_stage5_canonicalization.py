"""Unit Tests for Stage 5: Canonical Entities and Facts Creator.

Verifies:
- One canonical entity node per matched entity cluster (via DSU).
- Canonical entity preserves all original IDs as aliases (`aliases: [...]`) and provenance sources.
- Redirection of incoming/outgoing edges to canonical IDs.
- Deduplication of equivalent facts.
- Preservation of complementary facts from both graphs.
"""

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.assertions.confidence import Confidence, ConfidenceMethod
from core.assertions.state import AssertionState
from core.entities.context import Context
from core.evidence.evidence import Evidence
from core.fusion.canonicalizer import Canonicalizer
from core.fusion.meaning_aligner import MeaningAligner
from core.fusion.normalizer import DataNormalizer
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin, Provenance
from sdk.domain_config import (
    DomainFusionConfig,
    MappingDirection,
    MeaningAlignmentConfig,
    MeaningMapping,
    get_synthetic_preset,
)


def _make_test_assertion(
    a_id: str,
    subj: str,
    pred: str,
    obj: str,
    *,
    confidence: float | None = None,
    evidence: tuple[Evidence, ...] = (),
    source_graph: str | None = None,
) -> Assertion:
    conf = (
        Confidence(score=confidence, method=ConfidenceMethod.STATISTICAL)
        if confidence is not None
        else None
    )
    return Assertion(
        id=Identifier(namespace="ASSERT", value=a_id),
        subject=Identifier(namespace="ENTITY", value=subj),
        predicate=pred,
        object=Identifier(namespace="ENTITY", value=obj),
        confidence=conf,
        evidence=evidence,
        provenance=Provenance(
            agent_id=Identifier(namespace="SYS", value="test_agent"),
            activity_id=Identifier(namespace="SYS", value="test_act"),
            asserted_at=datetime.now(UTC),
            graph_origin_id=source_graph,
        ),
    )


def test_canonical_entity_aliases_and_edge_redirection() -> None:
    config = get_synthetic_preset()
    normalizer = DataNormalizer(config)
    canonicalizer = Canonicalizer(config)

    # Graph A assertions
    graph_a_assertions = [
        _make_test_assertion("a1", "Alice_A", "employedBy", "TechCorp_A"),
        _make_test_assertion("a2", "Alice_A", "locatedIn", "London"),
    ]
    # Graph B assertions
    graph_b_assertions = [
        _make_test_assertion("b1", "Alice_B", "employedBy", "TechCorp_B"),
        _make_test_assertion("b2", "Alice_B", "manages", "ProjectX"),
    ]

    norm_a = normalizer.normalize_graph(graph_a_assertions, "graph_a")
    norm_b = normalizer.normalize_graph(graph_b_assertions, "graph_b")

    # Match Alice_A <-> Alice_B and TechCorp_A <-> TechCorp_B
    auto_merged_pairs = [("Alice_A", "Alice_B"), ("TechCorp_A", "TechCorp_B")]

    res = canonicalizer.canonicalize(
        norm_a,
        norm_b,
        graph_a_assertions,
        graph_b_assertions,
        auto_merged_pairs,
    )

    # 1. Check canonical entities created
    assert res.canonical_entities_count >= 2

    # Check Alice canonical node has both aliases preserved
    alice_node = next(n for n in res.canonical_entities.values() if "Alice" in n["label"])
    assert "Alice_A" in alice_node["aliases"]
    assert "Alice_B" in alice_node["aliases"]
    assert len(alice_node["provenance_sources"]) >= 2

    # 2. Check edge redirection: all edges now point to canonical IDs
    canonical_subj_ids = {str(a.subject.value) for a in res.canonicalized_assertions}
    canonical_obj_ids = {str(a.object.value) for a in res.canonicalized_assertions}

    assert "Alice_B" not in canonical_subj_ids  # Redirected!
    assert "TechCorp_B" not in canonical_obj_ids  # Redirected!


def test_literal_property_canonicalization_from_aligned_assertions() -> None:
    """Verify literal properties are extracted from Stage 3 aligned assertions."""
    # Configure Stage 3 attribute mapping: fullName -> name
    attr_map = MeaningMapping(
        source_concept="fullName",
        target_concept="name",
        direction=MappingDirection.DIRECTED_A_TO_B,
    )
    domain_config = DomainFusionConfig(
        meaning_alignment=MeaningAlignmentConfig(attribute_mappings=(attr_map,)),
    )
    normalizer = DataNormalizer(domain_config)
    aligner = MeaningAligner(domain_config)
    canonicalizer = Canonicalizer(domain_config)

    # Graph A has literal assertion with unaligned predicate fullName
    a_assertions = [
        _make_test_assertion("a_lit", "Alice_A", "fullName", "Alice_Smith", source_graph="graph_a"),
    ]
    # Graph B has literal assertion with age
    b_assertions = [
        _make_test_assertion("b_lit", "Alice_B", "age", "30", source_graph="graph_b"),
    ]

    norm_a = normalizer.normalize_graph(a_assertions, "graph_a")
    norm_b = normalizer.normalize_graph(b_assertions, "graph_b")

    aligned_a = aligner.align_assertions(norm_a, "graph_a")
    aligned_b = aligner.align_assertions(norm_b, "graph_b")

    auto_merged_pairs = [("Alice_A", "Alice_B")]

    res = canonicalizer.canonicalize(
        norm_a,
        norm_b,
        aligned_a,
        aligned_b,
        auto_merged_pairs,
        graph_a_id=Identifier(namespace="GRAPH", value="source_alpha"),
        graph_b_id=Identifier(namespace="GRAPH", value="source_beta"),
    )

    alice_node = res.canonical_entities["Alice_A"]
    lit_props = alice_node["literal_properties"]

    # 1. Verify Stage 3 aligned predicate 'name' is present (not unaligned 'fullName')
    assert "name" in lit_props
    name_entry = lit_props["name"][0]
    assert name_entry["value"] == "Alice_Smith"
    assert name_entry["source_graph"] == "source_alpha"
    assert isinstance(name_entry["provenance"], Provenance)
    assert name_entry["provenance"].agent_id.value == "test_agent"

    # 2. Verify 'age' is present with source_beta
    assert "age" in lit_props
    age_entry = lit_props["age"][0]
    assert age_entry["value"] == 30
    assert age_entry["source_graph"] == "source_beta"

    # 3. Verify properties dictionary contains raw values
    assert alice_node["properties"]["name"] == "Alice_Smith"
    assert alice_node["properties"]["age"] == 30


def test_edge_redirection_deterministic_id_and_metadata_retention() -> None:
    """Verify edge redirection creates deterministic IDs and preserves all metadata."""
    config = get_synthetic_preset()
    normalizer = DataNormalizer(config)
    canonicalizer = Canonicalizer(config)

    ev = Evidence(
        id=Identifier(namespace="EVID", value="ev_hr"),
        record_id=Identifier(namespace="REC", value="rec_hr"),
        detail={"description": "Observed in HR payroll registry"},
    )
    ctx = Context(location="test_office", conditions={"temporal": "2026"})
    b_assertion = Assertion(
        id=Identifier(namespace="ASSERT", value="b_edge"),
        subject=Identifier(namespace="SRC_B", value="Alice_B"),
        predicate="manages",
        object=Identifier(namespace="SRC_B", value="ProjectX"),
        context=ctx,
        confidence=Confidence(score=0.92, method=ConfidenceMethod.STATISTICAL),
        evidence=(ev,),
        provenance=Provenance(
            agent_id=Identifier(namespace="SYS", value="hr_agent"),
            activity_id=Identifier(namespace="SYS", value="hr_act"),
            asserted_at=datetime.now(UTC),
            graph_origin_id="graph_b",
        ),
        status_at_creation=AssertionState.CANDIDATE,
    )

    norm_a = normalizer.normalize_graph([], "graph_a")
    norm_b = normalizer.normalize_graph([b_assertion], "graph_b")

    auto_merged_pairs = [("Alice_A", "Alice_B")]

    res1 = canonicalizer.canonicalize(norm_a, norm_b, [], [b_assertion], auto_merged_pairs)
    res2 = canonicalizer.canonicalize(norm_a, norm_b, [], [b_assertion], auto_merged_pairs)

    # 1. Deterministic ID generation
    assert len(res1.canonicalized_assertions) == 1
    redirected = res1.canonicalized_assertions[0]
    assert redirected.id.canonical.startswith("ASSERT:canon_")
    assert redirected.id.canonical == res2.canonicalized_assertions[0].id.canonical

    # 2. Redirected subject points to Alice_A
    assert redirected.subject.value == "Alice_A"

    # 3. Metadata retention
    assert redirected.confidence is not None
    assert redirected.confidence.score == 0.92
    assert len(redirected.evidence) == 1
    assert redirected.evidence[0].detail["description"] == "Observed in HR payroll registry"
    assert redirected.context == ctx
    assert redirected.status_at_creation == AssertionState.CANDIDATE

    # 4. Strict derived provenance
    assert redirected.provenance.assertion_origin == AssertionOrigin.DERIVED
    assert redirected.provenance.derivation_method == "canonical_edge_redirection"
    assert redirected.provenance.input_assertion_refs == (b_assertion.id,)


def test_canonical_triple_deduplication_and_provenance_aggregation() -> None:
    """Verify duplicate canonical triples across graphs are deduplicated and aggregated."""
    config = get_synthetic_preset()
    normalizer = DataNormalizer(config)
    canonicalizer = Canonicalizer(config)

    ev_a = Evidence(
        id=Identifier(namespace="EVID", value="ev_a"),
        record_id=Identifier(namespace="REC", value="rec_a"),
        detail={"description": "Graph A evidence"},
    )
    ev_b = Evidence(
        id=Identifier(namespace="EVID", value="ev_b"),
        record_id=Identifier(namespace="REC", value="rec_b"),
        detail={"description": "Graph B evidence"},
    )

    # Identical fact in Graph A and Graph B
    a1 = _make_test_assertion(
        "a1", "Alice_A", "employedBy", "TechCorp_A", confidence=0.85, evidence=(ev_a,)
    )
    b1 = _make_test_assertion(
        "b1", "Alice_B", "employedBy", "TechCorp_B", confidence=0.95, evidence=(ev_b,)
    )

    norm_a = normalizer.normalize_graph([a1], "graph_a")
    norm_b = normalizer.normalize_graph([b1], "graph_b")

    auto_merged_pairs = [("Alice_A", "Alice_B"), ("TechCorp_A", "TechCorp_B")]

    res = canonicalizer.canonicalize(norm_a, norm_b, [a1], [b1], auto_merged_pairs)

    # 1. Verify exact deduplication
    assert res.deduplicated_facts_count == 1
    assert len(res.canonicalized_assertions) == 1
    assert res.complementary_facts_count == 1

    merged = res.canonicalized_assertions[0]

    # 2. Canonical endpoints
    assert merged.subject.value == "Alice_A"
    assert merged.object.value == "TechCorp_A"

    # 3. Aggregated input assertion references
    assert a1.id in merged.provenance.input_assertion_refs
    assert b1.id in merged.provenance.input_assertion_refs
    assert merged.provenance.derivation_method == "canonical_deduplication"

    # 4. Merged evidence
    assert len(merged.evidence) == 2
    assert ev_a in merged.evidence
    assert ev_b in merged.evidence

    # 5. Calibrated confidence (higher score 0.95 retained)
    assert merged.confidence is not None
    assert merged.confidence.score == 0.95
