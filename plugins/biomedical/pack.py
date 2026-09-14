"""Biomedical Domain Pack implementation."""

from __future__ import annotations

from typing import Any

from plugins.biomedical.entities import (
    ActiveMoiety,
    ChemicalEntity,
    Disease,
    Drug,
    DrugProduct,
    Gene,
    Pathway,
    Protein,
)
from plugins.biomedical.relations import (
    RELATION_CONTRACTS,
)
from sdk.domain_config import DomainFusionConfig, get_biomedical_preset
from sdk.manifest import PluginManifest


class BiomedicalDomainPack:
    """Domain pack implementing biomedical entities and relations."""

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="biomedical_domain_pack",
            name="Biomedical Domain Pack",
            version="1.0.0",
            core_api_version="1.0.0",
            dependencies=[],
            capabilities=[
                "biomedical_entity_resolution",
                "biomedical_relation_validation",
                "biomedical_graph_projection",
            ],
            entities=[
                "Gene",
                "Protein",
                "ChemicalEntity",
                "Drug",
                "DrugProduct",
                "ActiveMoiety",
                "Disease",
                "Pathway",
            ],
            relations=list(RELATION_CONTRACTS.keys()),
            identifier_registries=[
                "hgnc",
                "ensembl",
                "uniprot",
                "chebi",
                "mondo",
                "chembl",
            ],
            identity_policies=["biomedical_identity_policy_v1"],
            validators=[
                "BIO-TYPE-001",
                "BIO-TAXON-001",
                "BIO-DRUG-001",
                "BIO-ISOFORM-001",
                "BIO-GRANULARITY-001",
                "BIO-EVIDENCE-001",
                "BIO-ID-001",
            ],
            evidence_policies=["biomedical_evidence_policy_v1"],
            projection_profiles=["biomedical_projection_profile_v1"],
            ai_assets=[],
        )

    def pack_components(self) -> dict[str, Any]:
        return {
            "schemas": {
                "Gene": Gene,
                "Protein": Protein,
                "ChemicalEntity": ChemicalEntity,
                "Drug": Drug,
                "DrugProduct": DrugProduct,
                "ActiveMoiety": ActiveMoiety,
                "Disease": Disease,
                "Pathway": Pathway,
            },
            "ontologies": {
                "hgnc": "http://www.genenames.org/",
                "uniprot": "http://purl.uniprot.org/uniprot/",
                "chebi": "http://purl.obolibrary.org/obo/CHEBI_",
                "mondo": "http://purl.obolibrary.org/obo/MONDO_",
                "chembl": "http://rdf.ebi.ac.uk/resource/chembl/molecule/",
            },
            "identifiers": {
                "hgnc": {"prefix": "HGNC"},
                "ensembl": {"prefix": "ENSG"},
                "uniprot": {"prefix": "UniProtKB"},
                "chebi": {"prefix": "CHEBI"},
                "mondo": {"prefix": "MONDO"},
                "chembl": {"prefix": "CHEMBL"},
            },
            "identity_policies": {},
            "rules": RELATION_CONTRACTS,
            "validators": {},
            "evidence_policies": {},
            "projections": {},
            "domain_config": get_biomedical_preset(),
        }

    def get_domain_config(self) -> DomainFusionConfig:
        """Return the domain fusion configuration for this plugin."""
        return get_biomedical_preset()

    def get_default_artifacts(self) -> list[dict[str, Any]]:
        """Return authentic sample biomedical dataset artifacts for release pipeline execution."""
        content = (
            b"@prefix chembl: <urn:chembl:> .\n"
            b"@prefix uniprot: <urn:uniprot:> .\n"
            b"@prefix hgnc: <urn:hgnc:> .\n"
            b"@prefix mondo: <urn:mondo:> .\n\n"
            b"chembl:CHEMBL25 <urn:biomedical:targets> uniprot:P00533 ;\n"
            b'    <urn:biomedical:name> "Aspirin" ;\n'
            b"    a <urn:biomedical:Drug> .\n\n"
            b"hgnc:HGNC_6018 <urn:biomedical:encodes> uniprot:P01308 ;\n"
            b"    <urn:biomedical:associated_with> mondo:0005148 ;\n"
            b'    <urn:biomedical:symbol> "INS" ;\n'
            b"    a <urn:biomedical:Gene> .\n"
        )
        return [
            {
                "name": "biomedical_domain_pack_seed_data.ttl",
                "content": content,
                "media_type": "turtle",
            }
        ]
