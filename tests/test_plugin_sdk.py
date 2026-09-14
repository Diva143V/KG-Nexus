"""Contract and compatibility tests for Plugin SDK (Phase 15)."""

import pytest

from plugins.synthetic import SyntheticDomainPack
from sdk.loader import IncompatiblePluginError, PluginLoader
from sdk.manifest import PluginManifest
from sdk.registries import PluginRegistry


def test_plugin_manifest_validation():
    manifest = PluginManifest(
        plugin_id="test_plugin",
        name="Test Plugin",
        version="1.0.0",
        core_api_version="1.0.0",
    )
    assert manifest.plugin_id == "test_plugin"
    assert manifest.core_api_version == "1.0.0"


def test_plugin_loader_success():
    registry = PluginRegistry()
    loader = PluginLoader(registry)

    pack = SyntheticDomainPack()
    loader.load(pack.manifest, pack.pack_components())

    assert registry.is_registered("synthetic_domain_pack")
    assert registry.get_plugin("synthetic_domain_pack") is not None
    assert registry.capabilities.has("synthetic_entity_resolution")
    assert registry.schemas.get("Person") is not None
    assert registry.identity_policies.get("synthetic_identity_policy_v1") is not None
    assert registry.projections.get("synthetic_projection_profile_v1") is not None


def test_plugin_loader_incompatible_api_version():
    registry = PluginRegistry()
    loader = PluginLoader(registry)

    manifest = PluginManifest(
        plugin_id="incompatible_plugin",
        name="Incompatible Plugin",
        version="1.0.0",
        core_api_version="99.0.0",
    )

    with pytest.raises(IncompatiblePluginError, match="not supported"):
        loader.load(manifest)


def test_plugin_loader_missing_dependency():
    registry = PluginRegistry()
    loader = PluginLoader(registry)

    manifest = PluginManifest(
        plugin_id="dependent_plugin",
        name="Dependent Plugin",
        version="1.0.0",
        core_api_version="1.0.0",
        dependencies=["non_existent_plugin"],
    )

    with pytest.raises(IncompatiblePluginError, match="missing required dependency"):
        loader.load(manifest)
