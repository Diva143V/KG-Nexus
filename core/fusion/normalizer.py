"""Stage 1: Data Normalization Module for Knowledge Graph Fusion.

Responsibilities:
- Distinguish between typed Literals (values: "Alice", 250, dates) and Entities (nodes: people, companies, places, genes, etc.)
- Keep literals strictly as values; never convert them into entity nodes just because text matches an entity label.
- Standardize labels, formats, and identifiers (ISO dates, numeric parsing, quote stripping).
- Produce normalized entities and relational assertions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.assertions.assertion import Assertion
from core.entities.entity import Entity, EntityKind
from core.resources.source_node import SourceNode, validate_source_uri
from sdk.domain_config import DomainFusionConfig, LiteralRuleConfig


def extract_local_name(iri_or_str: str) -> str:
    """Extract local name from IRI, CURIE, or path string."""
    s = iri_or_str.strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    if "#" in s:
        s = s.rsplit("#", 1)[-1]
    elif "/" in s:
        s = s.rsplit("/", 1)[-1]
    elif ":" in s and not (
        s.startswith("http://") or s.startswith("https://") or s.startswith("urn:")
    ):
        s = s.split(":", 1)[-1]
    return s.strip()


def normalize_label_text(label: str, role_suffixes: tuple[str, ...] = ()) -> str:
    """Domain-neutral string label normalization, stripping IRI prefixes, CURIEs & role suffixes."""
    s = label.strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    if "#" in s:
        s = s.rsplit("#", 1)[-1]
    elif "/" in s:
        s = s.rsplit("/", 1)[-1]
    if ":" in s and not (
        s.startswith("http://") or s.startswith("https://") or s.startswith("urn:")
    ):
        s = s.split(":", 1)[-1]

    # Lowercase & strip non-alphanumeric chars
    cleaned = re.sub(r"[^\w\s]", "", s.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Strip configured entity role suffixes (e.g. " drug", " gene", " inc")
    for suf in role_suffixes:
        pattern_space = f" {suf.lower()}"
        if cleaned.endswith(pattern_space):
            cleaned = cleaned[: -len(pattern_space)].strip()
            break

    # Strip underscore suffixes (e.g. "_drug", "_gene", "_inc")
    if role_suffixes:
        joined_suffixes = "|".join(re.escape(suf) for suf in role_suffixes)
        raw_clean = re.sub(rf"_({joined_suffixes})$", "", s, flags=re.IGNORECASE)
        if raw_clean != s:
            cleaned = re.sub(r"[^\w\s]", "", raw_clean.lower()).strip()

    return cleaned


def is_literal_value(
    predicate_name: str,
    object_value: str,
    literal_rules: LiteralRuleConfig,
) -> bool:
    """Determine if a triple object is a literal value rather than an entity node."""
    p_local = extract_local_name(predicate_name).lower()

    # 1. Check if predicate is an identifier/attribute property (e.g. chembl_id, hgnc_id, molecularWeight)
    if (
        p_local.endswith("_id")
        or p_local.endswith("_code")
        or p_local.endswith("id")
        or p_local.endswith("code")
        or p_local.endswith("weight")
        or p_local.endswith("formula")
        or p_local in ("id", "code", "sku", "gtin", "upc", "uuid", "key", "formula")
    ):
        return True

    # 2. Check if predicate is in literal_predicates list
    for lit_pred in literal_rules.literal_predicates:
        if p_local == lit_pred.lower() or p_local.endswith(lit_pred.lower()):
            return True

    # 3. Check for explicit RDF literal datatype annotations or xml schema types
    s = object_value.strip()
    if "^^" in s:
        return True

    # 4. Check for quoted string representation: "Alice", '250'
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return True

    # 5. Check for pure numeric format (int or float)
    if re.match(r"^-?\d+(\.\d+)?$", s):
        return True

    # 6. Check for boolean literal
    if s.lower() in ("true", "false", "yes", "no"):
        return True

    # 7. Check for standard date pattern (YYYY-MM-DD or YYYY/MM/DD)
    if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}(T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:?\d{2})?)?$", s):
        return True

    return False


def normalize_literal_format(
    val: str, literal_rules: LiteralRuleConfig
) -> str | int | float | bool:
    """Format and standardize literal values (dates to ISO, numbers, quote stripping)."""
    s = val.strip()

    # Strip RDF datatype suffix if present e.g. "250"^^xsd:integer
    if "^^" in s:
        s = s.split("^^")[0].strip()

    if literal_rules.strip_quotes:
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()

    # Check boolean
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False

    # Check numeric casting if enabled
    if literal_rules.auto_cast_numbers:
        if re.match(r"^-?\d+$", s):
            try:
                return int(s)
            except ValueError:
                pass
        elif re.match(r"^-?\d+\.\d+$", s):
            try:
                return float(s)
            except ValueError:
                pass

    # Normalize dates if enabled
    if literal_rules.normalize_dates_to_iso:
        for fmt in literal_rules.date_formats:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

    return s


@dataclass
class NormalizedGraph:
    """Result of Stage 1 Data Normalization."""

    graph_id: str
    entities: dict[str, Entity] = field(default_factory=dict)
    literal_properties: dict[tuple[str, str], list[Any]] = field(default_factory=dict)
    relational_assertions: list[Assertion] = field(default_factory=list)
    literal_assertions: list[Assertion] = field(default_factory=list)
    source_nodes: dict[str, SourceNode] = field(default_factory=dict)
    normalized_literals_count: int = 0
    normalized_entities_count: int = 0


class DataNormalizer:
    """Executes Stage 1: Data Normalization."""

    def __init__(self, domain_config: DomainFusionConfig) -> None:
        self.domain_config = domain_config

    def normalize_graph(
        self,
        assertions: list[Assertion],
        graph_id: str,
        sources: Sequence[SourceNode] | None = None,
    ) -> NormalizedGraph:
        """Normalize assertions into typed entities, literal properties, sources, and standardized triples."""
        norm_graph = NormalizedGraph(graph_id=graph_id)

        # Ingest explicit source nodes if provided
        if sources:
            for s in sources:
                for rule in self.domain_config.source_identity.supported_schemes:
                    if s.canonical_uri.lower().startswith(rule.scheme_prefix.lower()):
                        validate_source_uri(s.canonical_uri, rule, s.content_digest)
                        break
                norm_graph.source_nodes[s.id.value] = s

        for a in assertions:
            s_raw = a.subject.value
            p_raw = a.predicate
            o_raw = a.object.value

            # Extract implicit source references from assertion provenance if not already indexed
            for ref in a.provenance.input_resource_refs:
                ref_val = ref.value
                if ref_val not in norm_graph.source_nodes:
                    canonical_uri = ref_val
                    category = "internal"
                    for rule in self.domain_config.source_identity.supported_schemes:
                        if rule.scheme_prefix.lower() in ref_val.lower() or any(
                            v.lower() in ref_val.lower() for v in rule.strip_prefix_variants
                        ):
                            canonical_uri = validate_source_uri(ref_val, rule)
                            category = rule.category
                            break
                    if canonical_uri == ref_val and ":" not in ref_val:
                        canonical_uri = ref.canonical

                    norm_graph.source_nodes[ref_val] = SourceNode(
                        id=ref,
                        label=ref_val,
                        canonical_uri=canonical_uri,
                        category=category,
                    )

            # Ensure subject is treated as an entity node
            if s_raw not in norm_graph.entities:
                s_label = extract_local_name(s_raw)
                s_kind = self._infer_entity_kind(s_raw)
                norm_graph.entities[s_raw] = Entity(
                    id=a.subject,
                    kind=s_kind,
                    label=s_label,
                )

            # Check if object is a literal value vs entity node
            if is_literal_value(p_raw, o_raw, self.domain_config.literal_rules):
                # Process as literal value (do NOT create an entity node)
                norm_val = normalize_literal_format(o_raw, self.domain_config.literal_rules)
                p_local = extract_local_name(p_raw)
                prop_key = (s_raw, p_local)
                if prop_key not in norm_graph.literal_properties:
                    norm_graph.literal_properties[prop_key] = []
                norm_graph.literal_properties[prop_key].append(norm_val)

                if p_local.lower() in ("label", "name", "preflabel", "title") or p_raw.endswith(
                    ("#label", "/label", ":label", "#name", "/name")
                ):
                    val_str = str(norm_val).strip()
                    if val_str:
                        norm_graph.entities[s_raw].label = val_str

                norm_graph.literal_assertions.append(a)
                norm_graph.normalized_literals_count += 1
            else:
                # Process as relational assertion between two entity nodes
                if o_raw not in norm_graph.entities:
                    o_label = extract_local_name(o_raw)
                    o_kind = self._infer_entity_kind(o_raw)
                    norm_graph.entities[o_raw] = Entity(
                        id=a.object,
                        kind=o_kind,
                        label=o_label,
                    )

                norm_graph.relational_assertions.append(a)

        norm_graph.normalized_entities_count = len(norm_graph.entities)
        return norm_graph

    def _infer_entity_kind(self, entity_id_str: str) -> EntityKind:
        """Infer high-level entity kind from configured entity types in a domain-neutral manner."""
        s = entity_id_str.lower()
        for et in self.domain_config.entity_types:
            matches_prefix = any(prefix.lower() in s for prefix in et.namespace_prefixes)
            matches_name = et.name.lower() in s
            if matches_prefix or matches_name:
                kind_val = getattr(et, "kind", None)
                if isinstance(kind_val, EntityKind):
                    return kind_val
                if kind_val is not None:
                    k_str = str(getattr(kind_val, "value", kind_val)).lower()
                    for ek in EntityKind:
                        if ek.value == k_str:
                            return ek
                return EntityKind.CONCEPT
        return EntityKind.CONCEPT
