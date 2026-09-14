from __future__ import annotations

import pytest

from core.fusion.normalizer import DataNormalizer
from core.identifiers.identifier import Identifier
from core.resources.source_node import SourceNode
from sdk.domain_config import SourceSchemeRule, get_general_agnostic_preset


def test_source_regex_pattern_is_enforced():
    config = get_general_agnostic_preset().model_copy(
        update={
            "source_identity": get_general_agnostic_preset().source_identity.model_copy(
                update={
                    "supported_schemes": (
                        SourceSchemeRule(
                            scheme_prefix="urn:doi:",
                            regex_pattern=r"^10\\.\d{4,9}/[-._;()/:A-Za-z0-9]+$",
                        ),
                    ),
                }
            ),
        }
    )
    source = SourceNode(
        id=Identifier(namespace="SOURCE", value="bad"),
        label="Bad DOI",
        canonical_uri="urn:doi:not-a-doi",
    )

    with pytest.raises(ValueError, match="configured format"):
        DataNormalizer(config).normalize_graph([], "graph", sources=[source])


def test_required_internal_source_hash_is_enforced():
    config = get_general_agnostic_preset()
    source = SourceNode(
        id=Identifier(namespace="SOURCE", value="internal-1"),
        label="Internal report",
        canonical_uri="urn:internal:report-1",
    )

    with pytest.raises(ValueError, match="content hash"):
        DataNormalizer(config).normalize_graph([], "graph", sources=[source])
