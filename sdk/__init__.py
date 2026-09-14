"""Extension contracts and Domain SDK for building domain-specific plugins and graph fusion configs.

Core depends on the SDK interfaces, never on plugin implementations.
"""

from sdk.domain_config import (
    DOMAIN_PRESETS,
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
    get_biomedical_preset,
    get_general_agnostic_preset,
    get_synthetic_preset,
    resolve_domain_config,
)
from sdk.source_resolver import DefaultSourceResolver, SourceResolverProtocol

__all__ = [
    "DOMAIN_PRESETS",
    "ConfidenceThresholds",
    "ConflictResolutionRules",
    "DefaultSourceResolver",
    "DomainFusionConfig",
    "EntityTypeConfig",
    "LiteralRuleConfig",
    "MappingDirection",
    "MatchStrategyConfig",
    "MeaningAlignmentConfig",
    "MeaningMapping",
    "SourceIdentityConfig",
    "SourceResolverProtocol",
    "SourceSchemeRule",
    "get_biomedical_preset",
    "get_general_agnostic_preset",
    "get_synthetic_preset",
    "resolve_domain_config",
]
