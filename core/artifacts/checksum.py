"""Deterministic content checksums for artifacts."""

from __future__ import annotations

import hashlib


class ArtifactChecksumService:
    """Computes content identifiers and sizes for artifacts."""

    def sha256(self, content: bytes) -> str:
        """Return the lowercase hex sha256 digest of ``content``."""
        return hashlib.sha256(content).hexdigest()

    def size_bytes(self, content: bytes) -> int:
        """Return the byte length of ``content``."""
        return len(content)
