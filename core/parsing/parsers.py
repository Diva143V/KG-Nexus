"""Source content parsers.

Currently supported media types:

* RDF/Turtle (``text/turtle``)
* RDF/XML (``application/rdf+xml``)
* NTriples (``application/n-triples``)
* JSON-LD (``application/ld+json``)
* CSV (``text/csv``)

Parsers are minimal and deterministic; they extract raw records without
any semantic interpretation.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Protocol

import rdflib

from core.identifiers.identifier import Identifier
from core.parsing.errors import ParsingError
from core.resources.parsed_record import ParsedRecord, RecordStatus

MEDIA_TYPE_TURTLE = "text/turtle"
MEDIA_TYPE_JSON_LD = "application/ld+json"
MEDIA_TYPE_CSV = "text/csv"
MEDIA_TYPE_RDF_XML = "application/rdf+xml"
MEDIA_TYPE_NTRIPLES = "application/n-triples"


class SourceParser(Protocol):
    """Extension contract for parsing artifact content into records."""

    media_type: str

    def parse(
        self,
        content: bytes,
        *,
        artifact_id: Identifier,
        parsed_at: datetime,
    ) -> list[ParsedRecord]: ...


class TurtleParser:
    """Extracts one record per RDF triple from Turtle content using RDFLib."""

    media_type = MEDIA_TYPE_TURTLE

    def parse(
        self,
        content: bytes,
        *,
        artifact_id: Identifier,
        parsed_at: datetime,
    ) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParsingError(f"invalid turtle encoding: {exc}") from exc

        g = rdflib.Graph()
        try:
            g.parse(data=text, format="turtle")
        except Exception as exc:
            err_msg = str(exc)
            if "not bound" in err_msg.lower() or "prefix" in err_msg.lower():
                try:
                    fallback_headers = "@prefix EX: <http://example.org/> .\n@prefix exa: <http://example.org/ns/a/> .\n@prefix exb: <http://example.org/ns/b/> .\n"
                    g.parse(data=fallback_headers + text, format="turtle")
                except Exception:
                    raise ParsingError(f"Turtle parsing error: {exc}") from exc
            else:
                raise ParsingError(f"Turtle parsing error: {exc}") from exc

        prefix_map = {prefix: str(ns) for prefix, ns in g.namespaces() if prefix}

        rec_counter = 1
        for s, p, o in sorted(g, key=lambda t: (str(t[0]), str(t[1]), str(t[2]))):
            record_id = Identifier(namespace="record", value=f"{artifact_id.value}:{rec_counter}")
            records.append(
                ParsedRecord(
                    id=record_id,
                    artifact_id=artifact_id,
                    record_type="turtle_triple",
                    payload={
                        "subject": str(s),
                        "predicate": str(p),
                        "object": str(o),
                        "objects": [str(o)],
                        "prefix_map": prefix_map,
                    },
                    parsed_at=parsed_at,
                )
            )
            rec_counter += 1

        return records


class JsonLdParser:
    """Extracts records from JSON-LD or Knowledge Graph JSON content (nodes, graphs, edges, or raw objects)."""

    media_type = MEDIA_TYPE_JSON_LD

    def parse(
        self,
        content: bytes,
        *,
        artifact_id: Identifier,
        parsed_at: datetime,
    ) -> list[ParsedRecord]:
        try:
            data = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParsingError(f"invalid JSON / JSON-LD content: {exc}") from exc

        records: list[ParsedRecord] = []

        if isinstance(data, dict):
            # Check if payload is a graph fusion release with explicit edges
            if isinstance(data.get("edges"), list) and data["edges"]:
                for idx, edge in enumerate(data["edges"], start=1):
                    record_id = Identifier(
                        namespace="record", value=f"{artifact_id.value}:edge_{idx}"
                    )
                    s = edge.get("from") or edge.get("subject") or edge.get("src")
                    p = (
                        edge.get("label")
                        or edge.get("predicate")
                        or edge.get("rel")
                        or "related_to"
                    )
                    o = edge.get("to") or edge.get("object") or edge.get("dst")
                    if not s or not o:
                        raise ParsingError(
                            f"Edge record {idx} missing required subject ('from'/'subject'/'src') "
                            f"or object ('to'/'object'/'dst'): {edge}"
                        )
                    records.append(
                        ParsedRecord(
                            id=record_id,
                            artifact_id=artifact_id,
                            record_type="graph_edge",
                            payload={"subject": s, "predicate": p, "object": o, "raw": edge},
                            parsed_at=parsed_at,
                        )
                    )
                return records

            if isinstance(data.get("assertions"), list) and data["assertions"]:
                for idx, a_dict in enumerate(data["assertions"], start=1):
                    record_id = Identifier(
                        namespace="record", value=f"{artifact_id.value}:assertion_{idx}"
                    )
                    records.append(
                        ParsedRecord(
                            id=record_id,
                            artifact_id=artifact_id,
                            record_type="graph_assertion",
                            payload=a_dict if isinstance(a_dict, dict) else {"object": str(a_dict)},
                            parsed_at=parsed_at,
                        )
                    )
                return records

            items = data.get("@graph", data.get("nodes", data))
        else:
            items = data

        if not isinstance(items, list):
            items = [items]

        for idx, item in enumerate(items, start=1):
            record_id = Identifier(namespace="record", value=f"{artifact_id.value}:{idx}")
            if isinstance(item, dict):
                records.append(
                    ParsedRecord(
                        id=record_id,
                        artifact_id=artifact_id,
                        record_type="jsonld_node",
                        payload=item,
                        parsed_at=parsed_at,
                    )
                )
            else:
                records.append(
                    ParsedRecord(
                        id=record_id,
                        artifact_id=artifact_id,
                        record_type="jsonld_node",
                        status=RecordStatus.ERROR,
                        errors=[f"item {idx}: expected JSON object"],
                        parsed_at=parsed_at,
                    )
                )

        return records


class CsvParser:
    """Extracts one record per row from CSV content."""

    media_type = MEDIA_TYPE_CSV

    def parse(
        self,
        content: bytes,
        *,
        artifact_id: Identifier,
        parsed_at: datetime,
    ) -> list[ParsedRecord]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParsingError(f"invalid CSV encoding: {exc}") from exc

        reader = csv.DictReader(io.StringIO(text))
        records: list[ParsedRecord] = []

        for lineno, row in enumerate(reader, start=2):
            record_id = Identifier(namespace="record", value=f"{artifact_id.value}:{lineno}")

            if None in row or any(v is None for v in row.values()):
                records.append(
                    ParsedRecord(
                        id=record_id,
                        artifact_id=artifact_id,
                        record_type="csv_row",
                        status=RecordStatus.ERROR,
                        errors=[f"line {lineno}: mismatched or missing CSV columns"],
                        parsed_at=parsed_at,
                    )
                )
            else:
                records.append(
                    ParsedRecord(
                        id=record_id,
                        artifact_id=artifact_id,
                        record_type="csv_row",
                        payload=dict(row),
                        parsed_at=parsed_at,
                    )
                )

        return records


class RdfXmlParser:
    """Extracts one record per RDF triple from RDF/XML content using RDFLib."""

    media_type = "application/rdf+xml"

    def parse(
        self,
        content: bytes,
        *,
        artifact_id: Identifier,
        parsed_at: datetime,
    ) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParsingError(f"invalid RDF/XML encoding: {exc}") from exc

        g = rdflib.Graph()
        try:
            g.parse(data=text, format="xml")
        except Exception as exc:
            raise ParsingError(f"RDF/XML parsing error: {exc}") from exc

        prefix_map = {prefix: str(ns) for prefix, ns in g.namespaces() if prefix}

        rec_counter = 1
        for s, p, o in sorted(g, key=lambda t: (str(t[0]), str(t[1]), str(t[2]))):
            record_id = Identifier(namespace="record", value=f"{artifact_id.value}:{rec_counter}")
            records.append(
                ParsedRecord(
                    id=record_id,
                    artifact_id=artifact_id,
                    record_type="rdfxml_triple",
                    payload={
                        "subject": str(s),
                        "predicate": str(p),
                        "object": str(o),
                        "objects": [str(o)],
                        "prefix_map": prefix_map,
                    },
                    parsed_at=parsed_at,
                )
            )
            rec_counter += 1

        return records


class NTriplesParser:
    """Extracts one record per RDF triple from NTriples content using RDFLib."""

    media_type = "application/n-triples"

    def parse(
        self,
        content: bytes,
        *,
        artifact_id: Identifier,
        parsed_at: datetime,
    ) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParsingError(f"invalid NTriples encoding: {exc}") from exc

        g = rdflib.Graph()
        try:
            g.parse(data=text, format="nt")
        except Exception as exc:
            raise ParsingError(f"NTriples parsing error: {exc}") from exc

        prefix_map = {prefix: str(ns) for prefix, ns in g.namespaces() if prefix}

        rec_counter = 1
        for s, p, o in sorted(g, key=lambda t: (str(t[0]), str(t[1]), str(t[2]))):
            record_id = Identifier(namespace="record", value=f"{artifact_id.value}:{rec_counter}")
            records.append(
                ParsedRecord(
                    id=record_id,
                    artifact_id=artifact_id,
                    record_type="ntriples_triple",
                    payload={
                        "subject": str(s),
                        "predicate": str(p),
                        "object": str(o),
                        "objects": [str(o)],
                        "prefix_map": prefix_map,
                    },
                    parsed_at=parsed_at,
                )
            )
            rec_counter += 1

        return records
