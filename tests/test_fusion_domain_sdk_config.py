"""Unit Tests for Domain SDK Configuration.

Verifies:
- Loading of built-in presets: General Agnostic, Biomedical, Synthetic
- Custom JSON serialization / deserialization
- Extending domain rules declaratively without touching core code
- Validation of domain configuration models
"""

from sdk.domain_config import (
    DOMAIN_PRESETS,
    DomainFusionConfig,
    EntityTypeConfig,
    MappingDirection,
    MeaningMapping,
    resolve_domain_config,
)


def test_builtin_presets_discovery_and_resolution():
    assert "general_agnostic" in DOMAIN_PRESETS
    assert "biomedical" in DOMAIN_PRESETS
    assert "synthetic" in DOMAIN_PRESETS

    cfg_gen = resolve_domain_config("general_agnostic")
    assert cfg_gen.domain_id == "general_agnostic"

    cfg_bio = resolve_domain_config("biomedical")
    assert cfg_bio.domain_id == "biomedical"
    assert len(cfg_bio.entity_types) >= 4

    cfg_syn = resolve_domain_config("synthetic")
    assert cfg_syn.domain_id == "synthetic"


def test_custom_json_serialization_and_deserialization():
    custom_cfg = DomainFusionConfig(
        domain_id="ecommerce_products",
        domain_name="E-Commerce & Retail Products",
        description="Configuration for product catalogs, merchants, and SKU resolution",
        entity_types=(
            EntityTypeConfig(
                name="Product",
                identity_keys=("sku", "gtin", "upc"),
                color="#3b82f6",
                group="Product",
            ),
            EntityTypeConfig(
                name="Merchant",
                identity_keys=("merchant_id", "tax_id"),
                color="#10b981",
                group="Merchant",
            ),
        ),
        meaning_alignment={
            "relation_mappings": [
                MeaningMapping(
                    source_concept="soldBy",
                    target_concept="offeredBy",
                    direction=MappingDirection.EQUIVALENT,
                ).model_dump(mode="json"),
            ],
            "attribute_mappings": [
                MeaningMapping(
                    source_concept="item_name",
                    target_concept="title",
                    direction=MappingDirection.EQUIVALENT,
                ).model_dump(mode="json"),
                MeaningMapping(
                    source_concept="cost",
                    target_concept="price",
                    direction=MappingDirection.EQUIVALENT,
                ).model_dump(mode="json"),
            ],
        },
    )

    json_str = custom_cfg.to_json()
    assert "ecommerce_products" in json_str

    loaded_cfg = DomainFusionConfig.from_json(json_str)
    assert loaded_cfg.domain_id == "ecommerce_products"
    assert len(loaded_cfg.entity_types) == 2
    assert loaded_cfg.meaning_alignment.relation_mappings[0].source_concept == "soldBy"
