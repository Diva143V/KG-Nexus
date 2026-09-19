"""Plugin Loader.

Validates plugin compatibility before loading and registers components
into the global or provided PluginRegistry. Reject incompatible plugins.
"""

from __future__ import annotations

from typing import Any

from sdk.manifest import PluginManifest
from sdk.registries import PluginRegistry

SUPPORTED_CORE_API_VERSIONS = {"1.0.0"}


class IncompatiblePluginError(Exception):
    """Raised when a plugin fails compatibility checks."""


class PluginLoader:
    """Loader responsible for validating and registering domain plugins."""

    def __init__(self, registry: PluginRegistry | None = None) -> None:
        self.registry = registry or PluginRegistry()

    def validate_compatibility(self, manifest: PluginManifest) -> None:
        """Check if plugin's core_api_version and dependencies are satisfied."""
        if manifest.core_api_version not in SUPPORTED_CORE_API_VERSIONS:
            raise IncompatiblePluginError(
                f"Plugin '{manifest.plugin_id}' requires core_api_version '{manifest.core_api_version}', "
                f"which is not supported (supported: {SUPPORTED_CORE_API_VERSIONS})."
            )

        for dep in manifest.dependencies:
            if not self.registry.is_registered(dep):
                raise IncompatiblePluginError(
                    f"Plugin '{manifest.plugin_id}' missing required dependency '{dep}'."
                )

    def load(
        self,
        manifest: PluginManifest,
        pack_components: dict[str, Any] | None = None,
    ) -> None:
        """Validate and load a plugin into the registry."""
        self.validate_compatibility(manifest)
        self.registry.register_plugin(manifest)

        for cap in manifest.capabilities:
            self.registry.capabilities.register(cap)

        if pack_components:
            for name, schema_cls in pack_components.get("schemas", {}).items():
                self.registry.schemas.register(name, schema_cls)

            for prefix, uri in pack_components.get("ontologies", {}).items():
                self.registry.ontologies.register(prefix, uri)

            for name, meta in pack_components.get("identifiers", {}).items():
                self.registry.identifiers.register(name, meta)

            for method, policy in pack_components.get("identity_policies", {}).items():
                self.registry.identity_policies.register(method, policy)

            for rule_id, rule in pack_components.get("rules", {}).items():
                self.registry.rules.register(rule_id, rule)

            for name, validator in pack_components.get("validators", {}).items():
                self.registry.validators.register(name, validator)

            for name, ev_policy in pack_components.get("evidence_policies", {}).items():
                self.registry.evidence_policies.register(name, ev_policy)

            for name, profile in pack_components.get("projections", {}).items():
                self.registry.projections.register(name, profile)

    def load_pack(self, pack: Any) -> Any:
        """Validate and load an instantiated domain pack into the registry."""
        manifest: PluginManifest = pack.manifest
        pack_components = pack.pack_components() if hasattr(pack, "pack_components") else None
        self.load(manifest, pack_components)
        self.registry.register_pack(manifest.plugin_id, pack)
        clean_name = manifest.plugin_id.replace("_domain_pack", "").replace("-", "_")
        self.registry.register_pack(clean_name, pack)
        return pack

    def discover_and_load_pack(self, pack_name: str) -> Any:
        """Dynamically discover, instantiate, validate and load a domain pack by name."""
        clean_name = pack_name.lower().replace("-", "_").replace("_domain_pack", "")
        existing = self.registry.get_pack(clean_name)
        if existing is not None:
            return existing

        import importlib

        try:
            mod = importlib.import_module(f"plugins.{clean_name}")
            for attr in dir(mod):
                if attr.endswith("DomainPack"):
                    pack_cls = getattr(mod, attr)
                    pack_instance = pack_cls()
                    return self.load_pack(pack_instance)
        except ImportError as exc:
            raise ValueError(f"Unknown or uninstalled domain pack '{pack_name}': {exc}") from exc

        raise ValueError(
            f"Domain pack '{pack_name}' could not be initialized — "
            f"no module 'plugins.{clean_name}' or DomainPack class found."
        )
