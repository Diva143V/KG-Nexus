from __future__ import annotations

import pytest

from core.parsing.errors import ParsingError
from core.parsing.parsers import CsvParser, JsonLdParser, TurtleParser
from core.resources.parsed_record import RecordStatus
from tests.helpers import ident, utc

ARTIFACT_ID = ident("artifact", "a-1")
PARSED_AT = utc(2026, 1, 1)


def test_turtle_extracts_triples() -> None:
    content = (
        b"# a comment\n"
        b"@prefix ex: <http://example.com/> .\n"
        b"ex:alice a ex:Person .\n"
        b"ex:alice ex:knows ex:bob .\n"
    )
    records = TurtleParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert len(records) == 2
    assert records[0].payload["subject"] == "http://example.com/alice"
    assert records[0].payload["predicate"] == "http://example.com/knows"
    assert records[0].payload["objects"] == ["http://example.com/bob"]
    assert records[1].payload["predicate"] == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def test_turtle_skips_comments_and_prefixes() -> None:
    content = b"# only a comment\n@prefix ex: <http://example.com/> .\n"
    records = TurtleParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert records == []


def test_turtle_marks_malformed_line_as_error() -> None:
    content = b"ex:alice ex:knows\n"
    with pytest.raises(ParsingError):
        TurtleParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)


def test_turtle_rejects_undecodable_content() -> None:
    with pytest.raises(ParsingError):
        TurtleParser().parse(b"\xff\xfe", artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)


def test_jsonld_parses_top_level_array() -> None:
    content = b'[{"name": "alice"}, {"name": "bob"}]'
    records = JsonLdParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert len(records) == 2
    assert records[0].payload == {"name": "alice"}
    assert records[1].payload == {"name": "bob"}


def test_jsonld_parses_single_object() -> None:
    content = b'{"name": "alice"}'
    records = JsonLdParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert len(records) == 1
    assert records[0].payload == {"name": "alice"}


def test_jsonld_parses_graph() -> None:
    content = b'{"@graph": [{"name": "a"}, {"name": "b"}]}'
    records = JsonLdParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert len(records) == 2


def test_jsonld_marks_non_object_node_as_error() -> None:
    content = b'["not-an-object"]'
    records = JsonLdParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert len(records) == 1
    assert records[0].status == RecordStatus.ERROR


def test_jsonld_rejects_invalid_json() -> None:
    with pytest.raises(ParsingError):
        JsonLdParser().parse(b"{nope", artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)


def test_csv_parses_rows_against_header() -> None:
    content = b"gene,value\ng1,1.5\ng2,2.5\n"
    records = CsvParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert len(records) == 2
    assert records[0].payload == {"gene": "g1", "value": "1.5"}
    assert records[1].payload == {"gene": "g2", "value": "2.5"}


def test_csv_marks_malformed_row_as_error() -> None:
    content = b"a,b,c\n1,2\n"
    records = CsvParser().parse(content, artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert len(records) == 1
    assert records[0].status == RecordStatus.ERROR


def test_csv_empty_content_yields_no_records() -> None:
    records = CsvParser().parse(b"", artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert records == []


def test_csv_header_only_yields_no_records() -> None:
    records = CsvParser().parse(b"a,b\n", artifact_id=ARTIFACT_ID, parsed_at=PARSED_AT)
    assert records == []
