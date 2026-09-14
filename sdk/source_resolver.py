"""Source Resolver extension contracts and implementations.

Enables domain plugins to provide cross-identifier resolution (e.g. PMID <-> DOI,
patent priority numbers <-> PCT application numbers, internal system cross-refs).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


@runtime_checkable
class SourceResolverProtocol(Protocol):
    """Extension contract for resolving cross-identifier aliases and ground-truth status."""

    def resolve_aliases(self, uri_or_id: str) -> list[str]:
        """Return known alternative identifiers/aliases for a given source URI."""
        ...

    def is_ground_truth(self, uri_or_id: str) -> bool:
        """Return whether the given source URI is designated as ultimate ground truth."""
        ...


class DefaultSourceResolver(BaseModel):
    """Configurable in-memory source resolver for domain-specific aliases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    alias_mapping: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="Mapping from primary/alias URI to tuple of equivalent URIs",
    )
    ground_truth_uris: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Set of URIs declared as ultimate ground truth",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            if "aliases" in d and "alias_mapping" not in d:
                d["alias_mapping"] = d.pop("aliases")
            if "alias_mapping" in d and isinstance(d["alias_mapping"], dict):
                norm_mapping = {}
                for k, v in d["alias_mapping"].items():
                    norm_mapping[str(k)] = (
                        tuple(str(x) for x in v) if isinstance(v, (list, tuple, set)) else (str(v),)
                    )
                d["alias_mapping"] = norm_mapping
            if "ground_truth_uris" in d and isinstance(d["ground_truth_uris"], (list, set)):
                d["ground_truth_uris"] = tuple(str(x) for x in d["ground_truth_uris"])
            return d
        return data

    def resolve_aliases(self, uri_or_id: str) -> list[str]:
        """Return all known aliases for the given URI."""
        cleaned = str(uri_or_id).strip().lower()
        results: set[str] = set()

        for key, aliases in self.alias_mapping.items():
            k_clean = key.strip().lower()
            a_cleans = [a.strip().lower() for a in aliases]
            if cleaned == k_clean or cleaned in a_cleans:
                results.add(key)
                results.update(aliases)

        # Remove the input uri if present and return sorted list
        results.discard(uri_or_id)
        return sorted(results)

    def is_ground_truth(self, uri_or_id: str) -> bool:
        """Check if URI matches any declared ground-truth pattern."""
        cleaned = str(uri_or_id).strip().lower()
        for gt in self.ground_truth_uris:
            if cleaned == gt.strip().lower():
                return True
        return False
