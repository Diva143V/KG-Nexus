"""Artifact-related domain errors."""

from __future__ import annotations


class ArtifactIntegrityError(RuntimeError):
    """Raised when a stored artifact's content digest does not match its recorded SHA-256."""
