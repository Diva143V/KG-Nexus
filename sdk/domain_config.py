"""Declarative Domain SDK and Mapping Configuration for Knowledge Graph Fusion.

Enables configuration-driven graph fusion across any domain without modifying core code:
- Entity types, identity keys, display labels, visual styling
- Directional or equivalence-aware class, predicate, and attribute mappings
- Multi-strategy candidate matching weights (exact, label, embedding, structural)
- Conservative confidence thresholds (auto-merge, review, keep separate)
- Conflict resolution rules (opposing predicates, functional properties, source authorities)
- Literal vs Entity typing rules
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MappingDirection(StrEnum):
    """Directionality for class, predicate, or attribute mappings."""

    EQUIVALENT = "equivalent"  # Bidirectional: A <-> B
    DIRECTED_A_TO_B = "directed_a_to_b"  # Unidirectional: A -> B
    DIRECTED_B_TO_A = "directed_b_to_a"  # Unidirectional: B -> A
    CANONICAL = "canonical"  # Both map to a canonical ontology concept


class EntityTypeKind(StrEnum):
    """Entity kind classification for domain-neutral entity typing."""

    CONCEPT = "concept"
    ORGANIZATION = "organization"
    LOCATION = "location"
    PERSON = "person"
    GENE = "gene"
    PROTEIN = "protein"
    DRUG = "drug"
    CHEMICAL = "chemical"
    DISEASE = "disease"


class EntityTypeConfig(BaseModel):
    """Configuration for a specific domain entity type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Entity type name (e.g. Person, Gene, Company)")
    namespace_prefixes: tuple[str, ...] = Field(
        default_factory=tuple,
        description="URI/IRI prefix substrings or namespace identifiers associated with this type",
    )
    identity_keys: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Property names used as primary identity keys (e.g. ['tax_id', 'email'], ['hgnc_id'])",
    )
    kind: EntityTypeKind = Field(
        default=EntityTypeKind.CONCEPT,
        description="Entity kind classification (concept, organization, location, person, gene, protein, drug, chemical, disease)",
    )
    alias_property_names: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Property names treated as aliases/synonyms for this entity type (e.g. ['symbol', 'gene_symbol'])",
    )
    display_label_template: str = Field(
        default="{label} ({type})",
        description="Template for formatting entity labels in UI/reports",
    )
    color: str = Field(default="#ff6b00", description="Hex color code for graph visualization")
    group: str = Field(default="Entity", description="Visual grouping category")


class LiteralRuleConfig(BaseModel):
    """Rules to distinguish and format typed literals vs entity nodes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    literal_predicates: tuple[str, ...] = Field(
        default_factory=lambda: (
            "name",
            "fullName",
            "title",
            "label",
            "description",
            "age",
            "yearsOld",
            "birthDate",
            "dateOfBirth",
            "foundedDate",
            "amount",
            "count",
            "value",
            "score",
            "confidence",
            "email",
            "phone",
            "url",
            "comment",
            "status",
            "chemicalFormula",
            "molecularWeight",
            "approvedDate",
            "chembl_id",
            "gene_symbol",
            "drug_name",
            "chemical_name",
            "disease_name",
        ),
        description="Predicates whose object values must always remain typed literals, never entity nodes",
    )
    date_formats: tuple[str, ...] = Field(
        default_factory=lambda: (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ),
        description="Supported date formats for normalization",
    )
    strip_quotes: bool = Field(
        default=True, description="Whether to strip surrounding quotes from literals"
    )
    normalize_dates_to_iso: bool = Field(
        default=True, description="Standardize dates to ISO-8601 strings"
    )
    auto_cast_numbers: bool = Field(
        default=True, description="Attempt numeric casting for integer/float values"
    )


class MeaningMapping(BaseModel):
    """A single directional or equivalence mapping between concepts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_concept: str = Field(min_length=1)
    target_concept: str = Field(min_length=1)
    direction: MappingDirection = Field(default=MappingDirection.EQUIVALENT)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    notes: str | None = None


class MeaningAlignmentConfig(BaseModel):
    """Ontology and vocabulary alignment configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    class_mappings: tuple[MeaningMapping, ...] = Field(
        default_factory=tuple,
        description="Class/Type mappings between Graph A and Graph B (e.g. TypeA <-> TypeB)",
    )
    relation_mappings: tuple[MeaningMapping, ...] = Field(
        default_factory=tuple,
        description="Relation/Predicate mappings (e.g. worksAt <-> employedBy)",
    )
    attribute_mappings: tuple[MeaningMapping, ...] = Field(
        default_factory=tuple,
        description="Attribute/Property mappings for literals (e.g. fullName <-> name)",
    )
    disjoint_classes: tuple[tuple[str, str], ...] = Field(
        default_factory=tuple,
        description="Pairs of classes that can never match (e.g. ('Person', 'Company'))",
    )
    standard_ontology_namespaces: tuple[str, ...] = Field(
        default_factory=lambda: ("ro_", "prov#", "w3.org", "schema.org", "skos", "qudt.org"),
        description="Standard ontology namespace substrings recognized as standard vocabulary",
    )
    ontology_shortage_fallback_iri: str = Field(
        default="http://www.w3.org/2004/02/skos/core#related",
        description="Default fallback IRI used when an unmapped predicate shortage is detected",
    )


class MatchStrategyConfig(BaseModel):
    """Weights and parameters for multi-strategy candidate matching."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enable_exact_id: bool = Field(
        default=True, description="Match by exact IRI, value, or identity keys"
    )
    enable_label_similarity: bool = Field(
        default=True, description="Match by normalized string and token similarity"
    )
    enable_structural_similarity: bool = Field(
        default=True, description="Match by 1-hop graph neighborhood overlap"
    )
    enable_embeddings: bool = Field(
        default=False,
        description="Match by vector embeddings (disabled by default to prevent non-deterministic/costly merges)",
    )
    label_similarity_threshold: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Minimum string/token similarity threshold for candidate matching",
    )
    embedding_model_id: str = Field(
        default="BAAI/bge-large-en-v1.5",
        description="Pre-trained semantic embedding model identifier (HuggingFace ID or local path)",
    )
    embedding_provider: str = Field(
        default="auto",
        description="Provider backend: 'auto', 'ollama', 'huggingface', or 'test_double'",
    )
    embedding_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity to consider an embedding match",
    )
    embedding_batch_size: int = Field(
        default=32,
        ge=1,
        le=512,
        description="Batch size for entity embedding inference",
    )
    exact_id_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    label_similarity_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    structural_similarity_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    embedding_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    strategy_version: str = Field(
        default="1.0.0", description="Version identifier for match strategy configuration"
    )
    label_substring_match_score: float = Field(
        default=0.75, ge=0.0, le=1.0, description="Score for label substring matches"
    )
    normalized_label_threshold: float = Field(
        default=0.90, ge=0.0, le=1.0, description="Threshold for normalized label method selection"
    )
    structural_neighborhood_threshold: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Threshold for structural neighborhood method selection",
    )
    role_suffixes_to_strip: tuple[str, ...] = Field(
        default_factory=lambda: (
            "_Drug",
            "_Target",
            "_Disease",
            "inc",
            "corp",
            "ltd",
            "llc",
            "org",
            "co",
            "group",
        ),
        description="Common role suffixes to strip during label normalization",
    )


class ConfidenceThresholds(BaseModel):
    """Conservative confidence thresholds for match decisioning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    high_confidence_threshold: float = Field(
        default=0.88,
        ge=0.0,
        le=1.0,
        description="Score >= threshold merges automatically into canonical entity",
    )
    review_threshold: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Score >= review_threshold and < high_confidence sends for human/model review",
    )
    # Below review_threshold: KEEP_SEPARATE (never merge)


class ConflictResolutionRules(BaseModel):
    """Rules governing conflicting values and assertion precedence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    opposing_predicates: tuple[tuple[str, str], ...] = Field(
        default_factory=lambda: (
            ("treats", "contraindicates"),
            ("contraindicates", "treats"),
            ("employedBy", "terminatedBy"),
            ("terminatedBy", "employedBy"),
            ("active", "inactive"),
            ("inactive", "active"),
            ("approved", "rejected"),
            ("rejected", "approved"),
        ),
        description="Pairs of predicates that contradict each other for identical (subject, object)",
    )
    functional_predicates: tuple[str, ...] = Field(
        default_factory=lambda: (
            "birthDate",
            "dateOfBirth",
            "foundedDate",
            "capitalCity",
            "officialName",
            "ceo",
        ),
        description="Single-valued predicates that can have at most one canonical value per subject",
    )
    predicate_authorities: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping from predicate to authoritative source graph (e.g. {'gene_symbol': 'graph_a'})",
    )
    default_graph_precedence: str = Field(
        default="graph_a",
        description="Default tie-breaker graph ('graph_a', 'graph_b', or 'confidence')",
    )


class SourceSchemeRule(BaseModel):
    """Rules for validating, normalizing, and resolving a URI scheme."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scheme_prefix: str = Field(
        min_length=1,
        description="Scheme prefix, e.g. 'urn:doi:', 'urn:patent:', 'https://', 'urn:internal:'",
    )
    category: str = Field(
        default="publication",
        description="Generic category: publication, patent, web, internal, ground_truth",
    )
    regex_pattern: str | None = Field(
        default=None, description="Regex pattern for format validation"
    )
    strip_prefix_variants: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Prefix variants to strip during normalization (e.g. ('https://doi.org/', 'doi:'))",
    )
    lowercase_value: bool = Field(default=True, description="Whether to lowercase normalized value")
    require_content_hash: bool = Field(
        default=False, description="Mandatory SHA-256 for internal unversioned files"
    )


class SourceIdentityConfig(BaseModel):
    """Configuration for source modeling, universal URIs, and ultimate ground truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    supported_schemes: tuple[SourceSchemeRule, ...] = Field(default_factory=tuple)
    enable_source_alignment: bool = Field(
        default=True, description="Automatically align matching source nodes"
    )
    allow_manual_override_uris: bool = Field(
        default=True, description="Support expert pinned canonical URIs"
    )
    ground_truth_sources: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Tuple of source canonical URIs declared as ultimate ground truth",
    )
    corroboration_confidence_boost: float = Field(
        default=0.10,
        ge=0.0,
        le=0.5,
        description="Confidence boost when an assertion is corroborated by independent source nodes",
    )


class DomainFusionConfig(BaseModel):
    """Complete domain-specific configuration for general-purpose knowledge graph fusion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain_id: str = Field(default="general_agnostic", description="Unique domain identifier")
    domain_name: str = Field(default="General Agnostic Domain", description="Human-friendly name")
    description: str = Field(
        default="Domain-neutral graph fusion configuration with conservative thresholds"
    )
    entity_types: tuple[EntityTypeConfig, ...] = Field(default_factory=tuple)
    literal_rules: LiteralRuleConfig = Field(default_factory=LiteralRuleConfig)
    meaning_alignment: MeaningAlignmentConfig = Field(default_factory=MeaningAlignmentConfig)
    match_strategy: MatchStrategyConfig = Field(default_factory=MatchStrategyConfig)
    confidence_thresholds: ConfidenceThresholds = Field(default_factory=ConfidenceThresholds)
    conflict_rules: ConflictResolutionRules = Field(default_factory=ConflictResolutionRules)
    source_identity: SourceIdentityConfig = Field(default_factory=SourceIdentityConfig)
    default_node_color: str = Field(
        default="#ff6b00", description="Default visualization color for subject nodes"
    )
    default_target_node_color: str = Field(
        default="#ffaa00", description="Default visualization color for object nodes"
    )
    fusion_policy_version: str = Field(
        default="1.0.0", description="Version of the fusion policy configuration"
    )

    def to_json(self, indent: int = 2) -> str:
        """Serialize configuration to JSON string."""
        return json.dumps(self.model_dump(mode="json"), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> DomainFusionConfig:
        """Deserialize configuration from JSON string."""
        data = json.loads(json_str)
        return cls.model_validate(data)

    @classmethod
    def from_file(cls, file_path: str | Path) -> DomainFusionConfig:
        """Load configuration from JSON file."""
        content = Path(file_path).read_text(encoding="utf-8")
        return cls.from_json(content)


# ============================================================================
# BUILT-IN PRESETS
# ============================================================================


# Module-level date format defaults (shared between LiteralRuleConfig and general preset)
_DATE_FORMATS_DEFAULTS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
)

# Module-level boolean defaults (shared between LiteralRuleConfig and general preset)
_STRIP_QUOTES_DEFAULT = True
_NORMALIZE_DATES_TO_ISO_DEFAULT = True
_AUTO_CAST_NUMBERS_DEFAULT = True

# Clean literal rules for general-agnostic domain (no domain-specific predicates)
_literal_rules_general = LiteralRuleConfig(
    literal_predicates=(
        "name",
        "fullName",
        "title",
        "label",
        "description",
        "age",
        "yearsOld",
        "birthDate",
        "dateOfBirth",
        "value",
        "confidence",
        "email",
        "phone",
        "url",
        "comment",
        "status",
    ),
    date_formats=_DATE_FORMATS_DEFAULTS,  # use module-level defaults
    strip_quotes=_STRIP_QUOTES_DEFAULT,
    normalize_dates_to_iso=_NORMALIZE_DATES_TO_ISO_DEFAULT,
    auto_cast_numbers=_AUTO_CAST_NUMBERS_DEFAULT,
)


def get_general_agnostic_preset() -> DomainFusionConfig:
    """Default conservative domain-agnostic fusion configuration."""
    return DomainFusionConfig(
        domain_id="general_agnostic",
        domain_name="General Domain-Agnostic Preset",
        description="Conservative neutral fusion rules suitable for general knowledge graphs.",
        entity_types=(
            EntityTypeConfig(name="Entity", color="#ff6b00", group="Entity"),
            EntityTypeConfig(name="Concept", color="#ffaa00", group="Concept"),
            EntityTypeConfig(
                name="Person", identity_keys=("email", "tax_id"), color="#3b82f6", group="Person"
            ),
            EntityTypeConfig(
                name="Organization",
                identity_keys=("org_id", "tax_id"),
                color="#10b981",
                group="Organization",
            ),
            EntityTypeConfig(name="Place", color="#8b5cf6", group="Place"),
        ),
        literal_rules=_literal_rules_general,
        meaning_alignment=MeaningAlignmentConfig(
            relation_mappings=(
                MeaningMapping(
                    source_concept="worksAt",
                    target_concept="employedBy",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="works_for",
                    target_concept="employedBy",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="locatedIn",
                    target_concept="basedIn",
                    direction=MappingDirection.EQUIVALENT,
                ),
            ),
            attribute_mappings=(
                MeaningMapping(
                    source_concept="fullName",
                    target_concept="name",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="yearsOld",
                    target_concept="age",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="dateOfBirth",
                    target_concept="birthDate",
                    direction=MappingDirection.EQUIVALENT,
                ),
            ),
        ),
        match_strategy=MatchStrategyConfig(enable_embeddings=False),
        confidence_thresholds=ConfidenceThresholds(
            high_confidence_threshold=0.88, review_threshold=0.65
        ),
        conflict_rules=ConflictResolutionRules(),
        source_identity=SourceIdentityConfig(
            supported_schemes=(
                SourceSchemeRule(
                    scheme_prefix="urn:doi:",
                    category="publication",
                    strip_prefix_variants=("https://doi.org/", "http://dx.doi.org/", "doi:"),
                ),
                SourceSchemeRule(scheme_prefix="urn:patent:", category="patent"),
                SourceSchemeRule(scheme_prefix="https://", category="web"),
                SourceSchemeRule(
                    scheme_prefix="urn:internal:", category="internal", require_content_hash=True
                ),
                SourceSchemeRule(scheme_prefix="urn:manual:", category="ground_truth"),
            ),
            enable_source_alignment=True,
            allow_manual_override_uris=True,
        ),
    )


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
    )


def get_synthetic_preset() -> DomainFusionConfig:
    """Domain preset for enterprise synthetic and organization graphs."""
    return DomainFusionConfig(
        domain_id="synthetic",
        domain_name="Enterprise & Synthetic Domain Preset",
        description="Configuration for people, companies, departments, and geographic locations.",
        entity_types=(
            EntityTypeConfig(
                name="Person",
                identity_keys=("email", "employee_id", "ssn"),
                color="#3b82f6",
                group="Person",
            ),
            EntityTypeConfig(
                name="Company",
                identity_keys=("duns", "vat_id", "tax_id"),
                color="#10b981",
                group="Company",
            ),
            EntityTypeConfig(
                name="Department", identity_keys=("dept_code",), color="#f59e0b", group="Department"
            ),
            EntityTypeConfig(
                name="Location",
                identity_keys=("geo_id", "postal_code"),
                color="#8b5cf6",
                group="Location",
            ),
        ),
        literal_rules=LiteralRuleConfig(),
        meaning_alignment=MeaningAlignmentConfig(
            class_mappings=(
                MeaningMapping(
                    source_concept="Organization",
                    target_concept="Company",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="Employee",
                    target_concept="Person",
                    direction=MappingDirection.EQUIVALENT,
                ),
            ),
            relation_mappings=(
                MeaningMapping(
                    source_concept="worksAt",
                    target_concept="employedBy",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="headquarteredIn",
                    target_concept="locatedIn",
                    direction=MappingDirection.EQUIVALENT,
                ),
            ),
            attribute_mappings=(
                MeaningMapping(
                    source_concept="fullName",
                    target_concept="name",
                    direction=MappingDirection.EQUIVALENT,
                ),
                MeaningMapping(
                    source_concept="foundedYear",
                    target_concept="foundedDate",
                    direction=MappingDirection.EQUIVALENT,
                ),
            ),
            disjoint_classes=(
                ("Person", "Company"),
                ("Person", "Location"),
            ),
        ),
        match_strategy=MatchStrategyConfig(
            enable_embeddings=False,
            embedding_model_id="BAAI/bge-large-en-v1.5",
            role_suffixes_to_strip=("inc", "corp", "ltd", "llc", "group", "co"),
        ),
        confidence_thresholds=ConfidenceThresholds(
            high_confidence_threshold=0.88, review_threshold=0.65
        ),
        conflict_rules=ConflictResolutionRules(
            opposing_predicates=(
                ("employedBy", "terminatedBy"),
                ("terminatedBy", "employedBy"),
                ("owns", "divested"),
            ),
            functional_predicates=("birthDate", "foundedDate", "ceo", "headquarters"),
        ),
        source_identity=SourceIdentityConfig(
            supported_schemes=(
                SourceSchemeRule(
                    scheme_prefix="urn:internal:", category="internal", require_content_hash=True
                ),
                SourceSchemeRule(scheme_prefix="https://", category="web"),
                SourceSchemeRule(scheme_prefix="urn:patent:", category="patent"),
                SourceSchemeRule(scheme_prefix="urn:manual:", category="ground_truth"),
            ),
            enable_source_alignment=True,
            allow_manual_override_uris=True,
        ),
    )


DOMAIN_PRESETS: dict[str, DomainFusionConfig] = {
    "general_agnostic": get_general_agnostic_preset(),
    "biomedical": get_biomedical_preset(),
    "synthetic": get_synthetic_preset(),
}


def resolve_domain_config(
    config_or_id: DomainFusionConfig | str | dict[str, Any] | None,
) -> DomainFusionConfig:
    """Resolve domain configuration from object, preset ID, or dictionary."""
    if config_or_id is None:
        return get_general_agnostic_preset()
    if isinstance(config_or_id, DomainFusionConfig):
        return config_or_id
    if isinstance(config_or_id, str):
        cid = config_or_id.lower().strip()
        if cid in DOMAIN_PRESETS:
            return DOMAIN_PRESETS[cid]
        # Attempt to parse JSON string
        try:
            return DomainFusionConfig.from_json(config_or_id)
        except Exception:
            return get_general_agnostic_preset()
    if isinstance(config_or_id, dict):
        return DomainFusionConfig.model_validate(config_or_id)
    return get_general_agnostic_preset()
