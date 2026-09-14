"""First-class Source entity representation in the Knowledge Graph.

Domain-neutral mechanics for modeling sources as explicit nodes with
universal URI schemes, cryptographic content digests, and ground-truth anchors.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from pydantic import ConfigDict, Field

from core.resources.resource import Resource


def compute_content_digest(content: bytes | str) -> str:
    """Compute deterministic SHA-256 hex digest for arbitrary file or payload content."""
    if isinstance(content, str):
        b = content.encode("utf-8")
    else:
        b = content
    return hashlib.sha256(b).hexdigest()


def normalize_source_uri(
    raw_uri: str,
    rule: Any | None = None,
    *,
    expected_prefix: str = "",
    strip_prefix_variants: Sequence[str] = (),
    lowercase_value: bool = True,
) -> str:
    """Standardize a raw source identifier into its canonical URI format."""
    s = str(raw_uri).strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()

    if rule is not None:
        expected_prefix = getattr(rule, "scheme_prefix", getattr(rule, "prefix", expected_prefix))
        strip_prefix_variants = getattr(rule, "strip_prefix_variants", strip_prefix_variants)
        lowercase_value = getattr(rule, "lowercase_value", lowercase_value)

    # Strip recognized prefix variants (e.g. 'https://doi.org/', 'http://dx.doi.org/', 'doi:')
    for variant in strip_prefix_variants:
        if s.lower().startswith(variant.lower()):
            s = s[len(variant) :].strip()
            break

    # Also strip redundant scheme prefix if passed in raw string
    if expected_prefix and s.lower().startswith(expected_prefix.lower()):
        s = s[len(expected_prefix) :].strip()

    # Format-specific standardization
    if expected_prefix.lower().startswith("urn:patent:"):
        s = re.sub(r"[,]+", "", s)
        s = re.sub(r"\s+", ":", s.strip())
        s = s.upper()
        # Handle compact patent numbers like EP3456789A1 -> EP:3456789:A1
        m = re.match(r"^([A-Z]{2})(\d+)([A-Z0-9]*)$", s)
        if m and ":" not in s:
            parts = [m.group(1), m.group(2)]
            if m.group(3):
                parts.append(m.group(3))
            s = ":".join(parts)
    elif lowercase_value:
        s = s.lower()

    # Ensure canonical prefix is prepended
    if expected_prefix:
        return f"{expected_prefix}{s}"
    return s


def validate_source_uri(raw_uri: str, rule: Any, content_digest: str | None = None) -> str:
    """Normalize and validate a source URI against its configured scheme rule."""
    canonical_uri = normalize_source_uri(raw_uri, rule)
    prefix = str(getattr(rule, "scheme_prefix", ""))
    value = (
        canonical_uri[len(prefix) :]
        if prefix and canonical_uri.startswith(prefix)
        else canonical_uri
    )
    pattern = getattr(rule, "regex_pattern", None)
    if pattern is not None and re.fullmatch(pattern, value) is None:
        raise ValueError(f"Source URI does not match configured format: {raw_uri}")
    if getattr(rule, "require_content_hash", False) and not content_digest:
        raise ValueError(f"Source requires a content hash: {raw_uri}")
    return canonical_uri


class SourceNode(Resource):
    """An explicit, immutable Source node in the Knowledge Graph.

    Represents any primary knowledge source (paper, patent, web resource,
    or internal enterprise report) as a first-class graph citizen.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str = Field(
        default="publication",
        description="Domain-neutral category: 'publication', 'patent', 'web', 'internal', etc.",
    )
    canonical_uri: str = Field(
        min_length=1,
        description="Standardized canonical URI (e.g. 'urn:doi:10.1038/...', 'urn:patent:US:11234567:B2')",
    )
    alternate_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Cross-identifier aliases (e.g. ('PMID:32839624', 'PMC:PMC7442444'))",
    )
    content_digest: str | None = Field(
        default=None,
        description="Cryptographic SHA-256 digest of content payload (mandatory for internal reports/assays)",
    )
    issued_date: str | None = Field(
        default=None,
        description="ISO-8601 publication, grant, or filing date",
    )
    publisher_or_assignee: str | None = Field(
        default=None,
        description="Publisher, journal, assignee, or organization responsible for this source",
    )
    is_ground_truth: bool = Field(
        default=False,
        description="Whether this source is an ultimate ground-truth authority",
    )
    authority_tier: int = Field(
        default=100,
        ge=1,
        description="Authority tier (1 = Ultimate Gold Standard, 10 = Verified Registry, 100 = General)",
    )
    pinned_canonical_uri: str | None = Field(
        default=None,
        description="Manually curated override URI designated by human expert",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Extensible key-value metadata (authors, license, assay type, etc.)",
    )

    @property
    def effective_canonical_uri(self) -> str:
        """Return pinned manual override URI if present, otherwise canonical_uri."""
        return self.pinned_canonical_uri or self.canonical_uri
