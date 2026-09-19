"""Biomedical domain fusion configuration preset."""

from __future__ import annotations

import re

from core.resources.source_node import register_scheme_normalizer
from sdk.domain_config import (
    ConfidenceThresholds,
    ConflictResolutionRules,
    DomainFusionConfig,
    EntityTypeConfig,
    LiteralRuleConfig,
    MappingDirection,
    MatchStrategyConfig,
    MeaningAlignmentConfig,
    MeaningMapping,
    SourceIdentityConfig,
    SourceSchemeRule,
    register_domain_preset,
)


def _normalize_patent_uri(val: str) -> str:
    s = re.sub(r"[,]+", "", val)
    s = re.sub(r"\s+", ":", s.strip()).upper()
    m = re.match(r"^([A-Z]{2})(\d+)([A-Z0-9]*)$", s)
    if m and ":" not in s:
        parts = [m.group(1), m.group(2)]
        if m.group(3):
            parts.append(m.group(3))
        s = ":".join(parts)
    return s


register_scheme_normalizer("urn:patent:", _normalize_patent_uri)
register_scheme_normalizer("patent", _normalize_patent_uri)


def get_biomedical_preset() -> DomainFusionConfig:
    """Domain preset for biomedical and pharmaceutical knowledge graphs."""
    return DomainFusionConfig(
        domain_id="biomedical",
        domain_name="Biomedical & Life Sciences Preset",
        description="Configuration for biomedical ontologies (HGNC, UniProt, ChEBI, MONDO, DrugBank).",
        entity_types=(
            EntityTypeConfig(
                name="Gene",
                namespace_prefixes=("hgnc", "gene"),
                identity_keys=("hgnc_id", "symbol"),
                color="#ff6b00",
                group="Gene",
            ),
            EntityTypeConfig(
                name="Protein",
                namespace_prefixes=("uniprot", "protein"),
                identity_keys=("uniprot_id", "accession"),
                color="#ffaa00",
                group="Protein",
            ),
            EntityTypeConfig(
                name="Drug",
                namespace_prefixes=("chembl", "drugbank", "drug"),
                identity_keys=("chembl_id", "cas_number"),
                color="#ff9100",
                group="Drug",
            ),
            EntityTypeConfig(
                name="Disease",
                namespace_prefixes=("mondo", "doid", "disease"),
                identity_keys=("mondo_id", "doid_id"),
                color="#e65100",
                group="Disease",
            ),
            EntityTypeConfig(
                name="Chemical",
                namespace_prefixes=("chebi", "pubchem"),
                identity_keys=("chebi_id", "cid"),
                color="#ffab40",
                group="Chemical",
            ),
        ),
        literal_rules=LiteralRuleConfig(
            literal_predicates=(
                "name",
                "fullName",
                "symbol",
                "description",
                "synonym",
                "molecularWeight",
                "iupacName",
                "weight",
                "formula",
                "chemicalFormula",
                "chembl_id",
                "gene_symbol",
                "drug_name",
                "chemical_name",
                "disease_name",
            ),
        ),
        meaning_alignment=MeaningAlignmentConfig(
            relation_mappings=(
                MeaningMapping(
                    source_concept="encodes",
                    target_concept="producesProtein",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="targets",
                    target_concept="modulates",
                    direction=MappingDirection.DIRECTED_A_TO_B,
                ),
                MeaningMapping(
                    source_concept="indicated_for",
                    target_concept="treats",
                    direction=MappingDirection.EQUIVALENT,
                ),
            ),
            attribute_mappings=(
                MeaningMapping(
                    source_concept="gene_symbol",
                    target_concept="symbol",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="prefLabel",
                    target_concept="name",
                    direction=MappingDirection.EQUIVALENT,
                ),
            ),
            disjoint_classes=(
                ("Gene", "Disease"),
                ("Drug", "Disease"),
            ),
        ),
        match_strategy=MatchStrategyConfig(
            enable_embeddings=False,
            embedding_model_id="cambridgeltl/SapBERT-from-PubMedBERT-fulltext",
            role_suffixes_to_strip=("drug", "gene", "protein", "disease", "compound"),
        ),
        confidence_thresholds=ConfidenceThresholds(
            high_confidence_threshold=0.88, review_threshold=0.65
        ),
        conflict_rules=ConflictResolutionRules(
            opposing_predicates=(
                ("treats", "contraindicates"),
                ("contraindicates", "treats"),
                ("inhibits", "activates"),
                ("activates", "inhibits"),
                ("causes", "prevents"),
                ("prevents", "causes"),
                ("increases", "decreases"),
                ("decreases", "increases"),
                ("positive_regulator", "negative_regulator"),
                ("negative_regulator", "positive_regulator"),
            ),
            predicate_authorities={"symbol": "graph_a", "encodes": "graph_a"},
        ),
        source_identity=SourceIdentityConfig(
            supported_schemes=(
                SourceSchemeRule(
                    scheme_prefix="urn:doi:",
                    category="publication",
                    strip_prefix_variants=("https://doi.org/", "http://dx.doi.org/", "doi:"),
                ),
                SourceSchemeRule(scheme_prefix="urn:pmid:", category="publication"),
                SourceSchemeRule(scheme_prefix="urn:pmc:", category="publication"),
                SourceSchemeRule(scheme_prefix="https://clinicaltrials.gov/", category="web"),
                SourceSchemeRule(scheme_prefix="urn:patent:", category="patent"),
                SourceSchemeRule(
                    scheme_prefix="urn:internal:", category="internal", require_content_hash=True
                ),
                SourceSchemeRule(scheme_prefix="urn:manual:", category="ground_truth"),
            ),
            enable_source_alignment=True,
            allow_manual_override_uris=True,
        ),
        target_projection_backend="rdf",
    )


register_domain_preset("biomedical", get_biomedical_preset)
