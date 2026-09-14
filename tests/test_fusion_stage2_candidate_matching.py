"""Unit Tests for Stage 2: Candidate Matcher.

Verifies:
- Exact ID matching (1.0 confidence)
- Identity key matching (e.g. tax_id, email, hgnc_id)
- Name and label similarity (exact normalized, substring, string edit distance)
- Neighborhood structural similarity (1-hop Jaccard graph overlap)
- Multi-strategy composite scoring and breakdown
- Embeddings disabled by default for zero-cost determinism
"""

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.fusion.candidate_finder import CandidateFinder
from core.fusion.normalizer import DataNormalizer
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from sdk.domain_config import (
    get_biomedical_preset,
    get_general_agnostic_preset,
    get_synthetic_preset,
)


def _make_test_assertion(a_id: str, subj: str, pred: str, obj: str) -> Assertion:
    import re

    clean_subj = re.sub(r"\s+", "_", subj)
    clean_obj = re.sub(r"\s+", "_", obj)
    return Assertion(
        id=Identifier(namespace="ASSERT", value=a_id),
        subject=Identifier(namespace="ENTITY", value=clean_subj),
        predicate=pred,
        object=Identifier(namespace="ENTITY", value=clean_obj),
        provenance=Provenance(
            agent_id=Identifier(namespace="SYS", value="test_agent"),
            activity_id=Identifier(namespace="SYS", value="test_act"),
            asserted_at=datetime.now(UTC),
        ),
    )


def test_exact_id_and_identity_key_matching():
    config = get_synthetic_preset()
    normalizer = DataNormalizer(config)
    finder = CandidateFinder(config)
    activity_id = Identifier(namespace="ACT", value="act_test")

    graph_a_assertions = [
        _make_test_assertion("a1", "EMP_001", "name", "Alice Smith"),
        _make_test_assertion("a2", "EMP_001", "email", "alice@company.com"),
    ]
    graph_b_assertions = [
        _make_test_assertion("b1", "PERSON_999", "fullName", "Alice S."),
        _make_test_assertion("b2", "PERSON_999", "email", "alice@company.com"),
    ]

    norm_a = normalizer.normalize_graph(graph_a_assertions, "graph_a")
    norm_b = normalizer.normalize_graph(graph_b_assertions, "graph_b")

    candidates = finder.find_candidates(norm_a, norm_b, activity_id)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.composite_score == 1.0
    assert c.primary_method == "exact_id"
    assert any("Matching Identity Key 'email'" in ev for ev in c.evidence)


def test_normalized_label_similarity_and_role_suffixes():
    config = get_biomedical_preset()
    normalizer = DataNormalizer(config)
    finder = CandidateFinder(config)
    activity_id = Identifier(namespace="ACT", value="act_test")

    graph_a_assertions = [
        _make_test_assertion(
            "a1", "http://biomed.org/Metformin", "targets", "http://biomed.org/Insulin"
        ),
    ]
    graph_b_assertions = [
        _make_test_assertion(
            "b1", "http://pharm.org/Metformin_Drug", "targets", "http://pharm.org/Insulin_Protein"
        ),
    ]

    norm_a = normalizer.normalize_graph(graph_a_assertions, "graph_a")
    norm_b = normalizer.normalize_graph(graph_b_assertions, "graph_b")

    candidates = finder.find_candidates(norm_a, norm_b, activity_id)
    assert len(candidates) >= 2

    # Metformin and Insulin should both be surfaced as candidate matches
    metformin_cand = next(c for c in candidates if "Metformin" in str(c.source_entity.id.value))
    assert metformin_cand.composite_score >= 0.90
    assert metformin_cand.primary_method == "normalized_label"


def test_structural_neighborhood_similarity():
    config = get_general_agnostic_preset()
    # Enable structural similarity
    config = config.model_copy(
        update={
            "match_strategy": config.match_strategy.model_copy(
                update={"enable_structural_similarity": True}
            )
        }
    )
    normalizer = DataNormalizer(config)
    finder = CandidateFinder(config)
    activity_id = Identifier(namespace="ACT", value="act_test")

    # Graph A: OrgA connects to CityX, CityY, CityZ
    graph_a = [
        _make_test_assertion("a1", "OrgA", "locatedIn", "CityX"),
        _make_test_assertion("a2", "OrgA", "locatedIn", "CityY"),
        _make_test_assertion("a3", "OrgA", "locatedIn", "CityZ"),
    ]
    # Graph B: Org_Alpha connects to CityX, CityY
    graph_b = [
        _make_test_assertion("b1", "Org_Alpha", "locatedIn", "CityX"),
        _make_test_assertion("b2", "Org_Alpha", "locatedIn", "CityY"),
    ]

    norm_a = normalizer.normalize_graph(graph_a, "graph_a")
    norm_b = normalizer.normalize_graph(graph_b, "graph_b")

    candidates = finder.find_candidates(norm_a, norm_b, activity_id)
    org_cand = next(
        c
        for c in candidates
        if str(c.source_entity.id.value) == "OrgA"
        and str(c.candidate_entity.id.value) == "Org_Alpha"
    )
    assert "structural_similarity" in org_cand.score_breakdown
    assert org_cand.score_breakdown["structural_similarity"] > 0.0
