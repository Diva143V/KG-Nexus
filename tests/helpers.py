"""Shared test helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from core.identifiers.identifier import Identifier


def ident(namespace: str, value: str) -> Identifier:
    """Build an Identifier for tests."""
    return Identifier(namespace=namespace, value=value)


def utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    """Build a timezone-aware UTC datetime for tests."""
    return datetime(year, month, day, hour, tzinfo=UTC)
