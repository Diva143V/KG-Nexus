"""Universal Source Aligner for Knowledge Graph Fusion.

Domain-neutral engine for aligning and canonicalizing source nodes across graphs:
1. Pass 0: Manual Override & Ground Truth Pinned URIs
2. Pass 1: Exact Canonical URI Match
3. Pass 2: Cryptographic Content Digest (SHA-256) Match (tamper-proof internal files)
4. Pass 3: Alternate ID / Cross-Reference Overlap
5. Pass 4: Pluggable Domain Resolver Lookup
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.identifiers.identifier import Identifier
from core.resources.source_node import SourceNode
from sdk.domain_config import DomainFusionConfig
from sdk.source_resolver import SourceResolverProtocol


@dataclass(frozen=True)
class AlignedSourcePair:
    """Audit record of two aligned source nodes across graphs."""

    source_a_id: str
    source_b_id: str
    canonical_id: str
    alignment_method: str
    is_ground_truth: bool
    evidence: str


@dataclass
class SourceAlignmentResult:
    """Result of cross-graph source alignment."""

    canonical_sources: dict[str, SourceNode] = field(default_factory=dict)
    source_alias_map: dict[str, str] = field(default_factory=dict)
    aligned_pairs: list[AlignedSourcePair] = field(default_factory=list)
    ground_truth_source_ids: set[str] = field(default_factory=set)


class SourceAligner:
    """Universal domain-neutral source alignment engine."""

    def __init__(
        self,
        domain_config: DomainFusionConfig,
        resolver: SourceResolverProtocol | None = None,
    ) -> None:
        self.domain_config = domain_config
        self.resolver = resolver

    def align_sources(
        self,
        sources_a: dict[str, SourceNode],
        sources_b: dict[str, SourceNode],
    ) -> SourceAlignmentResult:
        """Execute multi-pass alignment between sources in Graph A and Graph B."""
        result = SourceAlignmentResult()
        matched_b_ids: set[str] = set()

        config = self.domain_config.source_identity
        declared_ground_truth_uris = set(u.strip().lower() for u in config.ground_truth_sources)

        # Pre-populate ground truth sources from Graph A and Graph B
        for s_id, s_node in sources_a.items():
            is_gt = (
                s_node.is_ground_truth
                or s_node.authority_tier == 1
                or s_node.canonical_uri.strip().lower() in declared_ground_truth_uris
                or (
                    self.resolver is not None
                    and self.resolver.is_ground_truth(s_node.canonical_uri)
                )
            )
            if is_gt:
                result.ground_truth_source_ids.add(s_id)
                result.ground_truth_source_ids.add(s_node.canonical_uri)
                result.ground_truth_source_ids.add(s_node.effective_canonical_uri)

        for s_id, s_node in sources_b.items():
            is_gt = (
                s_node.is_ground_truth
                or s_node.authority_tier == 1
                or s_node.canonical_uri.strip().lower() in declared_ground_truth_uris
                or (
                    self.resolver is not None
                    and self.resolver.is_ground_truth(s_node.canonical_uri)
                )
            )
            if is_gt:
                result.ground_truth_source_ids.add(s_id)
                result.ground_truth_source_ids.add(s_node.canonical_uri)
                result.ground_truth_source_ids.add(s_node.effective_canonical_uri)

        # Iterate through Graph A sources and look for matches in Graph B
        for a_id, a_node in sources_a.items():
            best_b_id: str | None = None
            best_method: str | None = None
            best_evidence: str | None = None

            a_effective_uri = a_node.effective_canonical_uri.strip().lower()
            a_canonical_uri = a_node.canonical_uri.strip().lower()
            a_aliases = set(x.strip().lower() for x in a_node.alternate_ids)

            # Resolve external aliases via resolver if present
            if self.resolver is not None and config.enable_source_alignment:
                resolved = self.resolver.resolve_aliases(a_node.canonical_uri)
                a_aliases.update(x.strip().lower() for x in resolved)

            for b_id, b_node in sources_b.items():
                if b_id in matched_b_ids:
                    continue

                b_effective_uri = b_node.effective_canonical_uri.strip().lower()
                b_canonical_uri = b_node.canonical_uri.strip().lower()
                b_aliases = set(x.strip().lower() for x in b_node.alternate_ids)

                if self.resolver is not None and config.enable_source_alignment:
                    b_resolved = self.resolver.resolve_aliases(b_node.canonical_uri)
                    b_aliases.update(x.strip().lower() for x in b_resolved)

                # Track ground truth on B
                if (
                    b_node.is_ground_truth
                    or b_node.authority_tier == 1
                    or b_canonical_uri in declared_ground_truth_uris
                    or (
                        self.resolver is not None
                        and self.resolver.is_ground_truth(b_node.canonical_uri)
                    )
                ):
                    result.ground_truth_source_ids.add(b_id)

                # Pass 0: Manual Override Pinned URI
                if (
                    config.allow_manual_override_uris
                    and a_node.pinned_canonical_uri
                    and b_node.pinned_canonical_uri
                ):
                    if a_effective_uri == b_effective_uri:
                        best_b_id = b_id
                        best_method = "manual_pinned_uri_match"
                        best_evidence = (
                            f"Identical manual pinned URI: {a_node.pinned_canonical_uri}"
                        )
                        break

                # Pass 1: Exact Canonical URI Match
                if a_canonical_uri == b_canonical_uri or a_effective_uri == b_effective_uri:
                    best_b_id = b_id
                    best_method = "exact_canonical_uri_match"
                    best_evidence = f"Identical canonical URI: {a_node.canonical_uri}"
                    break

                # Pass 2: Cryptographic Content Digest Match (SHA-256)
                if (
                    a_node.content_digest is not None
                    and b_node.content_digest is not None
                    and a_node.content_digest.strip().lower()
                    == b_node.content_digest.strip().lower()
                ):
                    best_b_id = b_id
                    best_method = "cryptographic_content_digest_match"
                    best_evidence = f"Matching SHA-256 digest: {a_node.content_digest}"
                    break

                # Pass 3: Alternate ID / Cross-Reference Overlap
                overlap = a_aliases.intersection(b_aliases)
                if overlap:
                    best_b_id = b_id
                    best_method = "alternate_id_overlap_match"
                    best_evidence = f"Overlapping aliases: {sorted(overlap)}"
                    break

                # Check if B's canonical URI is in A's aliases or vice versa
                if b_canonical_uri in a_aliases or a_canonical_uri in b_aliases:
                    best_b_id = b_id
                    best_method = "cross_identifier_alias_match"
                    best_evidence = f"Cross-referenced URI: {a_canonical_uri} <-> {b_canonical_uri}"
                    break

            if best_b_id is not None and best_method is not None:
                matched_b_ids.add(best_b_id)
                b_match_node = sources_b[best_b_id]

                # Determine canonical representative
                # Ground truth / lower tier wins; tie-breaker: Graph A
                is_a_gt = a_id in result.ground_truth_source_ids
                is_b_gt = best_b_id in result.ground_truth_source_ids

                if is_b_gt and not is_a_gt:
                    canonical_id = best_b_id
                    winning_node = b_match_node
                else:
                    canonical_id = a_id
                    winning_node = a_node

                # Combine aliases and metadata
                merged_aliases = tuple(
                    sorted(set(a_node.alternate_ids) | set(b_match_node.alternate_ids))
                )
                merged_meta = dict(a_node.metadata)
                merged_meta.update(b_match_node.metadata)

                fused_source = SourceNode(
                    id=Identifier(namespace="SOURCE", value=canonical_id),
                    label=winning_node.label,
                    category=winning_node.category,
                    canonical_uri=winning_node.canonical_uri,
                    alternate_ids=merged_aliases,
                    content_digest=winning_node.content_digest
                    or a_node.content_digest
                    or b_match_node.content_digest,
                    issued_date=winning_node.issued_date
                    or a_node.issued_date
                    or b_match_node.issued_date,
                    publisher_or_assignee=winning_node.publisher_or_assignee
                    or a_node.publisher_or_assignee,
                    is_ground_truth=is_a_gt or is_b_gt,
                    authority_tier=min(a_node.authority_tier, b_match_node.authority_tier),
                    pinned_canonical_uri=winning_node.pinned_canonical_uri,
                    metadata=merged_meta,
                )

                result.canonical_sources[canonical_id] = fused_source
                result.source_alias_map[a_id] = canonical_id
                result.source_alias_map[best_b_id] = canonical_id

                pair_record = AlignedSourcePair(
                    source_a_id=a_id,
                    source_b_id=best_b_id,
                    canonical_id=canonical_id,
                    alignment_method=best_method,
                    is_ground_truth=is_a_gt or is_b_gt,
                    evidence=best_evidence or "",
                )
                result.aligned_pairs.append(pair_record)
            else:
                # Unmatched source in Graph A remains as its own canonical source
                result.canonical_sources[a_id] = a_node
                result.source_alias_map[a_id] = a_id

        # Retain unmatched sources in Graph B
        for b_id, b_node in sources_b.items():
            if b_id not in matched_b_ids:
                result.canonical_sources[b_id] = b_node
                result.source_alias_map[b_id] = b_id

        return result
