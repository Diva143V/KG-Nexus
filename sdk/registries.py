"""Domain Plugin Registries.

Maintains registries for capabilities, schemas, ontologies, identifiers,
identity policies, rules, validators, and projections loaded via plugins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from sdk.manifest import PluginManifest

if TYPE_CHECKING:
    from sdk.resolution import IdentityPolicy
    from sdk.validation import Validator


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: set[str] = set()

    def register(self, capability: str) -> None:
        self._capabilities.add(capability)

    def has(self, capability: str) -> bool:
        return capability in self._capabilities

    def all(self) -> set[str]:
        return set(self._capabilities)


class SchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, type[BaseModel]] = {}

    def register(self, name: str, schema_cls: type[BaseModel]) -> None:
        self._schemas[name] = schema_cls

    def get(self, name: str) -> type[BaseModel] | None:
        return self._schemas.get(name)

    def all(self) -> dict[str, type[BaseModel]]:
        return dict(self._schemas)


class OntologyRegistry:
    def __init__(self) -> None:
        self._namespaces: dict[str, str] = {}

    def register(self, prefix: str, uri: str) -> None:
        self._namespaces[prefix] = uri

    def get(self, prefix: str) -> str | None:
        return self._namespaces.get(prefix)

    def all(self) -> dict[str, str]:
        return dict(self._namespaces)


class IdentifierRegistry:
    def __init__(self) -> None:
        self._registries: dict[str, dict[str, Any]] = {}

    def register(self, name: str, metadata: dict[str, Any]) -> None:
        self._registries[name] = metadata

    def get(self, name: str) -> dict[str, Any] | None:
        return self._registries.get(name)

    def all(self) -> dict[str, dict[str, Any]]:
        return dict(self._registries)


class IdentityPolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, IdentityPolicy] = {}

    def register(self, method: str, policy: IdentityPolicy) -> None:
        self._policies[method] = policy

    def get(self, method: str) -> IdentityPolicy | None:
        return self._policies.get(method)

    def all(self) -> dict[str, IdentityPolicy]:
        return dict(self._policies)


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, Any] = {}

    def register(self, rule_id: str, rule: Any) -> None:
        self._rules[rule_id] = rule

    def get(self, rule_id: str) -> Any | None:
        return self._rules.get(rule_id)

    def all(self) -> dict[str, Any]:
        return dict(self._rules)


class ValidatorRegistry:
    def __init__(self) -> None:
        self._validators: dict[str, Validator] = {}

    def register(self, name: str, validator: Validator) -> None:
        self._validators[name] = validator

    def get(self, name: str) -> Validator | None:
        return self._validators.get(name)

    def all(self) -> dict[str, Validator]:
        return dict(self._validators)


class ProjectionRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, Any] = {}

    def register(self, name: str, profile: Any) -> None:
        self._profiles[name] = profile

    def get(self, name: str) -> Any | None:
        return self._profiles.get(name)

    def all(self) -> dict[str, Any]:
        return dict(self._profiles)


class EvidencePolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, Any] = {}

    def register(self, name: str, policy: Any) -> None:
        self._policies[name] = policy

    def get(self, name: str) -> Any | None:
        return self._policies.get(name)

    def all(self) -> dict[str, Any]:
        return dict(self._policies)


class FusionConfigRegistry:
    def __init__(self) -> None:
        from sdk.domain_config import DOMAIN_PRESETS, DomainFusionConfig

        self._configs: dict[str, DomainFusionConfig] = dict(DOMAIN_PRESETS)

    def register(self, name: str, config: Any) -> None:
        self._configs[name] = config

    def get(self, name: str) -> Any | None:
        return self._configs.get(name)

    def all(self) -> dict[str, Any]:
        return dict(self._configs)


class PluginRegistry:
    """Central registry holding loaded plugins and sub-registries."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginManifest] = {}
        self.capabilities = CapabilityRegistry()
        self.schemas = SchemaRegistry()
        self.ontologies = OntologyRegistry()
        self.identifiers = IdentifierRegistry()
        self.identity_policies = IdentityPolicyRegistry()
        self.rules = RuleRegistry()
        self.validators = ValidatorRegistry()
        self.evidence_policies = EvidencePolicyRegistry()
        self.projections = ProjectionRegistry()
        self.fusion_configs = FusionConfigRegistry()

    def register_plugin(self, manifest: PluginManifest) -> None:
        self._plugins[manifest.plugin_id] = manifest

    def get_plugin(self, plugin_id: str) -> PluginManifest | None:
        return self._plugins.get(plugin_id)

    def is_registered(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    def all_plugins(self) -> dict[str, PluginManifest]:
        return dict(self._plugins)
