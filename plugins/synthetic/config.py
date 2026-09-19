"""Synthetic domain fusion configuration preset."""

from __future__ import annotations

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
        literal_rules=LiteralRuleConfig(
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
                "sku",
                "gtin",
                "upc",
            )
        ),
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
                    source_concept="operatesIn",
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
        target_projection_backend="memory",
    )


register_domain_preset("synthetic", get_synthetic_preset)
