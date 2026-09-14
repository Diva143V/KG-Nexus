"""Plugin manifest definition.

Defines the metadata and declared capabilities, entities, relations,
policies, and assets for a domain plugin.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PluginManifest(BaseModel):
    """Manifest describing a domain plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plugin_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    core_api_version: str = Field(min_length=1, default="1.0.0")
    dependencies: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    identifier_registries: list[str] = Field(default_factory=list)
    identity_policies: list[str] = Field(default_factory=list)
    validators: list[str] = Field(default_factory=list)
    evidence_policies: list[str] = Field(default_factory=list)
    projection_profiles: list[str] = Field(default_factory=list)
    ai_assets: list[str] = Field(default_factory=list)
