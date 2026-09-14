"""Normalizer extension contract.

Normalizers transform raw values into normalized forms without deciding
domain meaning. Domain-specific normalizers (e.g. biomedical) implement
this contract; core provides domain-neutral built-ins.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Normalizer(Protocol):
    """Extension contract for a single normalization step."""

    @property
    def name(self) -> str:
        """Stable identifier for this normalizer."""
        ...

    @property
    def version(self) -> str:
        """Version of this normalizer, recorded in provenance."""
        ...

    def normalize(self, value: str) -> str:
        """Return the normalized form of ``value``."""
        ...
