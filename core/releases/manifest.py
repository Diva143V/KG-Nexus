"""Release manifests: the exact content a release references."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class LockfileSet(BaseModel):
    """Lockfiles pinned for a release, for reproducibility."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ontology: Identifier
    runtime: Identifier
    model: Identifier | None = None
    reasoner: Identifier
    projection: Identifier


class ReleaseManifest(BaseModel):
    """The exact references a release pins.

    A release references its source artifacts, assertions, policies,
    plugins, and the lockfiles that reproduce the build. The manifest is
    fixed when the release is created and never changes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_artifacts: tuple[Identifier, ...] = Field(default_factory=tuple)
    assertions: tuple[Identifier, ...] = Field(default_factory=tuple)
    policies: tuple[Identifier, ...] = Field(default_factory=tuple)
    plugins: tuple[Identifier, ...] = Field(default_factory=tuple)
    lockfiles: LockfileSet
