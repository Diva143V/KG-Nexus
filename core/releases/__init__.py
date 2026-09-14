"""Core release lifecycle: releases, manifests, gates, and the manager."""

from __future__ import annotations

from core.releases.errors import (
    InvalidReleaseTransitionError,
    PublishedReleaseError,
    ReleaseError,
    UnknownReleaseError,
)
from core.releases.manager import ReleaseManager
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release, ReleaseGate, ReleaseTransition
from core.releases.resolver import ReleaseStatusResolver
from core.releases.status import ReleaseStatus

__all__ = [
    "InvalidReleaseTransitionError",
    "LockfileSet",
    "PublishedReleaseError",
    "Release",
    "ReleaseError",
    "ReleaseGate",
    "ReleaseManager",
    "ReleaseManifest",
    "ReleaseStatus",
    "ReleaseStatusResolver",
    "ReleaseTransition",
    "UnknownReleaseError",
]
