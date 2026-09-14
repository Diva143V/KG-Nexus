"""Search document definitions.

A search document is the OpenSearch / Elasticsearch-shaped record the search
projection materializes: a stable document id, a kind, the Core-canonical
digest, plus the textual discovery fields — aliases, a label, a description,
and identifiers. ``text`` aggregates every searchable field so full-text
search covers aliases, labels, descriptions, and identifiers uniformly.

A document deliberately carries no state and no truth claim: search results
are retrieval candidates only, and search ranking must not directly promote
assertions.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Documented search fields carried on every document.
SEARCH_FIELDS = (
    "doc_id",
    "kind",
    "digest",
    "label",
    "description",
    "aliases",
    "identifiers",
    "text",
)

ENTITY = "entity"
RELATION = "relation"
ASSERTION = "assertion"


class SearchDocument(BaseModel):
    """One indexed search target (entity, relation, or assertion)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    digest: str = Field(min_length=1)
    label: str = Field(min_length=0)
    description: str = Field(min_length=0)
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    identifiers: tuple[str, ...] = Field(default_factory=tuple)
    text: str = Field(min_length=0)
