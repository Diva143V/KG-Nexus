"""Knowledge sources (e.g. publications or databases)."""

from __future__ import annotations

from enum import StrEnum

from core.resources.resource import Resource


class SourceKind(StrEnum):
    """Domain-neutral categories of knowledge sources."""

    PUBLICATION = "publication"
    DATABASE = "database"
    REPORT = "report"
    WEB = "web"
    OTHER = "other"


class Source(Resource):
    """A source of records, identified and labelled."""

    kind: SourceKind
    publisher: str | None = None
    licence: str | None = None
