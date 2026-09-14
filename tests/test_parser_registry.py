from __future__ import annotations

from datetime import datetime

import pytest

from core.identifiers.identifier import Identifier
from core.parsing.errors import UnsupportedMediaTypeError
from core.parsing.parser_registry import ParserRegistry
from core.parsing.parsers import (
    MEDIA_TYPE_CSV,
    MEDIA_TYPE_JSON_LD,
    MEDIA_TYPE_TURTLE,
    CsvParser,
)
from core.resources.parsed_record import ParsedRecord
from tests.helpers import ident, utc

ARTIFACT_ID = ident("artifact", "a-1")
PARSED_AT = utc(2026, 1, 1)


def test_default_parsers_registered() -> None:
    registry = ParserRegistry()
    assert registry.media_types() == (
        MEDIA_TYPE_JSON_LD,
        MEDIA_TYPE_CSV,
        MEDIA_TYPE_TURTLE,
    )
    assert registry.parser_for(MEDIA_TYPE_TURTLE) is not None
    assert registry.parser_for(MEDIA_TYPE_JSON_LD) is not None
    assert registry.parser_for(MEDIA_TYPE_CSV) is not None


def test_parser_for_unknown_returns_none() -> None:
    registry = ParserRegistry()
    assert registry.parser_for("application/xml") is None


def test_parse_unknown_media_type_raises() -> None:
    registry = ParserRegistry()
    with pytest.raises(UnsupportedMediaTypeError):
        registry.parse(
            b"x", artifact_id=ARTIFACT_ID, media_type="application/xml", parsed_at=PARSED_AT
        )


def test_parse_dispatches_by_media_type() -> None:
    registry = ParserRegistry()
    records = registry.parse(
        b"a,b\n1,2\n",
        artifact_id=ARTIFACT_ID,
        media_type=MEDIA_TYPE_CSV,
        parsed_at=PARSED_AT,
    )
    assert len(records) == 1
    assert records[0].payload == {"a": "1", "b": "2"}


def test_register_duplicate_media_type_raises() -> None:
    registry = ParserRegistry()
    with pytest.raises(ValueError):
        registry.register(CsvParser())


def test_register_custom_parser() -> None:
    class XmlParser:
        media_type = "application/xml"

        def parse(
            self,
            content: bytes,
            *,
            artifact_id: Identifier,
            parsed_at: datetime,
        ) -> list[ParsedRecord]:
            return []

    registry = ParserRegistry()
    registry.register(XmlParser())
    assert registry.parser_for("application/xml") is not None
