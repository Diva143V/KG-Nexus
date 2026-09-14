from __future__ import annotations

import hashlib

from core.artifacts.checksum import ArtifactChecksumService


def test_sha256_matches_hashlib() -> None:
    content = b"hello world"
    assert ArtifactChecksumService().sha256(content) == hashlib.sha256(content).hexdigest()


def test_size_bytes_matches_length() -> None:
    content = b"abc"
    assert ArtifactChecksumService().size_bytes(content) == 3


def test_sha256_is_deterministic() -> None:
    service = ArtifactChecksumService()
    assert service.sha256(b"x") == service.sha256(b"x")


def test_sha256_is_content_sensitive() -> None:
    service = ArtifactChecksumService()
    assert service.sha256(b"a") != service.sha256(b"b")
