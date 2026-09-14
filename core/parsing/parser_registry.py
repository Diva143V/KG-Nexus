"""Registry of parsers keyed by media type."""

from __future__ import annotations

from datetime import datetime

from core.identifiers.identifier import Identifier
from core.parsing.errors import ParsingError, UnsupportedMediaTypeError
from core.parsing.parsers import (
    MEDIA_TYPE_CSV,
    MEDIA_TYPE_JSON_LD,
    MEDIA_TYPE_NTRIPLES,
    MEDIA_TYPE_RDF_XML,
    MEDIA_TYPE_TURTLE,
    CsvParser,
    JsonLdParser,
    NTriplesParser,
    RdfXmlParser,
    SourceParser,
    TurtleParser,
)
from core.resources.parsed_record import ParsedRecord


class ParserRegistry:
    """Maps media types to parsers.

    Registered by default for RDF/Turtle, JSON-LD, and CSV.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, SourceParser] = {}
        for parser in (TurtleParser(), JsonLdParser(), CsvParser()):
            self.register(parser)

    def register(self, parser: SourceParser) -> None:
        key = parser.media_type
        if key in self._parsers:
            raise ValueError(f"duplicate parser for media type: {key}")
        self._parsers[key] = parser

    def parser_for(self, media_type: str) -> SourceParser | None:
        return self._parsers.get(media_type)

    def media_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._parsers))

    def parse(
        self,
        content: bytes,
        *,
        artifact_id: Identifier,
        media_type: str,
        parsed_at: datetime,
    ) -> list[ParsedRecord]:
        parser = self.parser_for(media_type)
        if parser is None:
            raise UnsupportedMediaTypeError(media_type)
        return parser.parse(content, artifact_id=artifact_id, parsed_at=parsed_at)


__all__ = [
    "MEDIA_TYPE_CSV",
    "MEDIA_TYPE_JSON_LD",
    "MEDIA_TYPE_TURTLE",
    "MEDIA_TYPE_RDF_XML",
    "MEDIA_TYPE_NTRIPLES",
    "CsvParser",
    "JsonLdParser",
    "RdfXmlParser",
    "NTriplesParser",
    "ParserRegistry",
    "ParsingError",
    "SourceParser",
    "TurtleParser",
    "UnsupportedMediaTypeError",
]
