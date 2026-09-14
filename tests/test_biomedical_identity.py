"""Tests for Biomedical Identity Rules and Identity Policy (Phase 18)."""

import pytest

from core.identifiers.identifier import Identifier
from core.resolution.models import CandidateMatch
from plugins.biomedical.entities import (
    ActiveMoiety,
    ChemicalEntity,
    DrugProduct,
    Gene,
    Protein,
)
from plugins.biomedical.identity import (
    BiomedicalIdentityDecisionKind,
    BiomedicalIdentityPolicy,
)


@pytest.fixture
def policy() -> BiomedicalIdentityPolicy:
    return BiomedicalIdentityPolicy()


@pytest.fixture
def act_id() -> Identifier:
    return Identifier(namespace="SYS", value="ACT_ID_1")


def test_positive_exact_identifier_matching(policy: BiomedicalIdentityPolicy):
    id1 = Identifier(namespace="HGNC", value="HGNC:6018")
    gene1 = Gene(id=id1, label="INS", tax_id="9606")
    gene2 = Gene(id=id1, label="INS", tax_id="9606")

    kind = policy.evaluate_pair(source=gene1, candidate=gene2)
    assert kind == BiomedicalIdentityDecisionKind.SAME_ENTITY


def test_hard_negative_gene_vs_protein(policy: BiomedicalIdentityPolicy):
    """HARD NEGATIVE: Gene and Protein cannot be merged as same entity."""
    g = Gene(id=Identifier(namespace="HGNC", value="HGNC:6018"), label="INS")
    p = Protein(id=Identifier(namespace="UniProtKB", value="P01308"), label="INS")

    kind = policy.evaluate_pair(source=g, candidate=p)
    assert kind == BiomedicalIdentityDecisionKind.REJECT
    assert kind != BiomedicalIdentityDecisionKind.SAME_ENTITY


def test_hard_negative_salt_vs_active_moiety(policy: BiomedicalIdentityPolicy):
    """HARD NEGATIVE: Salt / ChemicalEntity vs ActiveMoiety."""
    chem = ChemicalEntity(
        id=Identifier(namespace="CHEBI", value="CHEBI:6801"), label="Metformin HCl"
    )
    moiety = ActiveMoiety(id=Identifier(namespace="CHEBI", value="CHEBI:6800"), label="Metformin")

    kind = policy.evaluate_pair(source=chem, candidate=moiety)
    assert kind == BiomedicalIdentityDecisionKind.HAS_ACTIVE_MOIETY
    assert kind != BiomedicalIdentityDecisionKind.SAME_ENTITY


def test_hard_negative_drug_product_vs_chemical_entity(policy: BiomedicalIdentityPolicy):
    """HARD NEGATIVE: DrugProduct formulation cannot be merged with ChemicalEntity."""
    prod = DrugProduct(
        id=Identifier(namespace="NDC", value="0002-1431"), label="Glucophage 500mg Tablet"
    )
    chem = ChemicalEntity(id=Identifier(namespace="CHEBI", value="CHEBI:6800"), label="Metformin")

    kind = policy.evaluate_pair(source=prod, candidate=chem)
    assert kind == BiomedicalIdentityDecisionKind.REJECT


def test_hard_negative_cross_species(policy: BiomedicalIdentityPolicy):
    """HARD NEGATIVE: Human Gene vs Mouse Gene -> ORTHOLOGOUS_TO, not SAME_ENTITY."""
    human_gene = Gene(
        id=Identifier(namespace="HGNC", value="HGNC:6018"), label="INS", tax_id="9606"
    )
    mouse_gene = Gene(
        id=Identifier(namespace="MGI", value="MGI:96570"), label="Ins1", tax_id="10090"
    )

    kind = policy.evaluate_pair(source=human_gene, candidate=mouse_gene)
    assert kind == BiomedicalIdentityDecisionKind.ORTHOLOGOUS_TO
    assert kind != BiomedicalIdentityDecisionKind.SAME_ENTITY


def test_decide_accept_or_reject(policy: BiomedicalIdentityPolicy, act_id: Identifier):
    g1 = Gene(id=Identifier(namespace="HGNC", value="HGNC:6018"), label="INS", tax_id="9606")
    g2 = Gene(id=Identifier(namespace="HGNC", value="HGNC:6018"), label="INS", tax_id="9606")

    match = CandidateMatch(
        source_entity=g1,
        candidate_entity=g2,
        ranking_score=1.0,
        ranking_method="exact",
        activity_id=act_id,
    )
    decision = policy.decide(source=g1, candidate=match)
    assert decision.accepted is True
