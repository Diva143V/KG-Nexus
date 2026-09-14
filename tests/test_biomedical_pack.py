"""Tests for Biomedical Domain Pack (Phase 16)."""

from core.identifiers.identifier import Identifier
from core.relations.relation import Relation
from plugins.biomedical import (
    RELATION_CONTRACTS,
    BiomedicalDomainPack,
    Disease,
    Drug,
    Gene,
    Protein,
    derive_inverse_relation,
)
from sdk.loader import PluginLoader
from sdk.registries import PluginRegistry


def test_biomedical_pack_loading():
    registry = PluginRegistry()
    loader = PluginLoader(registry)
    pack = BiomedicalDomainPack()
    loader.load(pack.manifest, pack.pack_components())

    assert registry.is_registered("biomedical_domain_pack")
    assert registry.schemas.get("Gene") == Gene
    assert registry.schemas.get("Protein") == Protein
    assert registry.schemas.get("Drug") == Drug
    assert registry.schemas.get("Disease") == Disease


def test_biomedical_entities():
    gene_id = Identifier(namespace="HGNC", value="HGNC:6018")
    protein_id = Identifier(namespace="UniProtKB", value="P01308")
    disease_id = Identifier(namespace="MONDO", value="MONDO:0005148")

    gene = Gene(id=gene_id, label="INS", symbol="INS", tax_id="9606")
    protein = Protein(id=protein_id, label="Insulin", uniprot_id="P01308", tax_id="9606")
    disease = Disease(id=disease_id, label="Type 2 Diabetes", mondo_id="MONDO:0005148")

    assert gene.symbol == "INS"
    assert protein.uniprot_id == "P01308"
    assert disease.label == "Type 2 Diabetes"


def test_biomedical_relation_contracts_and_derived_inverse():
    assert "treats" in RELATION_CONTRACTS
    assert "treated_by" in RELATION_CONTRACTS
    assert RELATION_CONTRACTS["treated_by"].is_derived is True

    rel_id = Identifier(namespace="SYS", value="REL1")
    drug_id = Identifier(namespace="CHEMBL", value="CHEMBL1431")
    disease_id = Identifier(namespace="MONDO", value="MONDO:0005148")

    treats_rel = Relation(
        id=rel_id,
        subject=drug_id,
        predicate="treats",
        object=disease_id,
    )

    inverse_rel = derive_inverse_relation(treats_rel)
    assert inverse_rel is not None
    assert inverse_rel.subject == disease_id
    assert inverse_rel.predicate == "treated_by"
    assert inverse_rel.object == drug_id
