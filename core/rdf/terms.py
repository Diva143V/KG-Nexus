"""RDF terms: subjects, predicates, and objects.

Core models RDF with a minimal, deterministic term model instead of
depending on any single RDF library. Backends translate these terms into
concrete storage.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
XSD_DOUBLE = "http://www.w3.org/2001/XMLSchema#double"
XSD_BOOLEAN = "http://www.w3.org/2001/XMLSchema#boolean"
XSD_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"


class TermKind(StrEnum):
    """Categories of RDF terms."""

    IRI = "iri"
    BLANK = "blank"
    LITERAL = "literal"


class IRI(BaseModel):
    """An RDF IRI reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["iri"] = "iri"
    value: str = Field(min_length=1)


class BlankNode(BaseModel):
    """An RDF blank node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["blank"] = "blank"
    label: str = Field(min_length=1)


class RDFLiteral(BaseModel):
    """An RDF literal with an optional datatype or language tag.

    ``value`` is the lexical form; ``datatype`` and ``language`` are
    mutually exclusive.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["literal"] = "literal"
    value: str
    datatype: str | None = None
    language: str | None = None

    @model_validator(mode="after")
    def _datatype_or_language(self) -> Self:
        if self.datatype is not None and self.language is not None:
            raise ValueError("literal cannot carry both a datatype and a language tag")
        return self


RDFTerm = Annotated[IRI | BlankNode | RDFLiteral, Field(discriminator="kind")]


class Triple(BaseModel):
    """A single subject-predicate-object statement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: RDFTerm
    predicate: IRI
    object: RDFTerm

    @model_validator(mode="after")
    def _subject_is_not_literal(self) -> Self:
        if isinstance(self.subject, RDFLiteral):
            raise ValueError("an RDF subject cannot be a literal")
        return self


def iri(value: str) -> IRI:
    """Build an IRI term."""
    return IRI(value=value)


def blank(label: str) -> BlankNode:
    """Build a blank node term."""
    return BlankNode(label=label)


def string_literal(value: str) -> RDFLiteral:
    """Build an ``xsd:string`` literal."""
    return RDFLiteral(value=value, datatype=XSD_STRING)
