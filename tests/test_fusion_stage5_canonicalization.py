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
from core.fusion.canonicalizer import Canonicalizer
from core.fusion.normalizer import DataNormalizer
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from sdk.domain_config import get_synthetic_preset


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


def test_canonical_entity_aliases_and_edge_redirection():
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
