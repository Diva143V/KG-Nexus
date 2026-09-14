"""Tests for Biomedical Source Authority and Conflict Strategies (Phase 19)."""

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from plugins.biomedical.authority import (
    BiomedicalSourceAuthority,
    ConflictStrategy,
)


def _make_assertion(assertion_id: str, predicate: str, source_ns: str) -> Assertion:
    prov = Provenance(
        agent_id=Identifier(namespace=source_ns, value="agent_1"),
        activity_id=Identifier(namespace="SYS", value="act_1"),
        asserted_at=datetime.now(UTC),
    )
    return Assertion(
        id=Identifier(namespace="ASSERT", value=assertion_id),
        subject=Identifier(namespace="HGNC", value="HGNC:6018"),
        predicate=predicate,
        object=Identifier(namespace="MONDO", value="MONDO:0005148"),
        provenance=prov,
    )


def test_predicate_specific_source_preference():
    authority = BiomedicalSourceAuthority()
    assert authority.get_preferred_source("gene_symbol") == "hgnc"
    assert authority.get_preferred_source("protein_sequence") == "uniprot"
    assert authority.get_preferred_source("drug_bioactivity") == "chembl"
    assert authority.get_preferred_source("disease_cross_reference") == "mondo"


def test_strategy_preferred_source_wins():
    authority = BiomedicalSourceAuthority()
    a_hgnc = _make_assertion("a1", "encodes", "hgnc")
    a_other = _make_assertion("a2", "encodes", "other_source")

    res = authority.resolve_conflict(
        a_hgnc, a_other, ConflictStrategy.PREFERRED_SOURCE_WINS_WITH_PROVENANCE
    )
    assert res.winning_assertion == a_hgnc
    assert len(res.preserved_assertions) == 2
    assert res.flagged_for_review is False


def test_strategy_preserve_conflict_and_review():
    authority = BiomedicalSourceAuthority()
    a1 = _make_assertion("a1", "treats", "chembl")
    a2 = _make_assertion("a2", "treats", "fda")

    res = authority.resolve_conflict(a1, a2, ConflictStrategy.PRESERVE_CONFLICT_AND_REVIEW)
    assert res.winning_assertion is None
    assert len(res.preserved_assertions) == 2
    assert res.flagged_for_review is True


def test_strategy_preserve_source_specific_assertions():
    authority = BiomedicalSourceAuthority()
    a1 = _make_assertion("a1", "targets", "chembl")
    a2 = _make_assertion("a2", "targets", "pubchem")

    res = authority.resolve_conflict(a1, a2, ConflictStrategy.PRESERVE_SOURCE_SPECIFIC_ASSERTIONS)
    assert res.winning_assertion is None
    assert len(res.preserved_assertions) == 2
    assert res.flagged_for_review is False
