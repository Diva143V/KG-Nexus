"""Knowledge Graph Fusion Subsystem Orchestrator (6-Stage Pipeline)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.assertions.assertion import Assertion
from core.fusion.engine import GenericFusionEngine
from core.fusion.models import ConflictMode, FusionRun, GraphFusionRequest, GraphFusionResult
from core.identifiers.identifier import Identifier
from core.parsing.parser_registry import ParserRegistry
from core.parsing.parsers import MEDIA_TYPE_CSV, MEDIA_TYPE_JSON_LD, MEDIA_TYPE_TURTLE
from core.provenance.provenance import AssertionOrigin, Provenance
from core.resources.parsed_record import RecordStatus
from sdk.domain_config import DomainFusionConfig, resolve_domain_config


def sanitize_id_value(val: Any, default: str | None = None) -> str | None:
    if val is None:
        return default
    s = str(val).strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    clean = re.sub(r"\s+", "_", s)
    return clean if clean else default


def extract_field(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        val = payload.get(k)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def compute_policy_digest(config: DomainFusionConfig) -> str:
    """Compute SHA-256 digest of the domain configuration for policy tracking."""
    config_json = config.to_json()
    return hashlib.sha256(config_json.encode()).hexdigest()[:16]


UNKNOWN_FALLBACK_VALUE: str = "unknown"


def get_project_version() -> str:
    """Read project version from pyproject.toml."""
    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("version"):
                        # Extract version from "version = "0.0.0""
                        version = line.split("=")[1].strip().strip('"').strip("'")
                        return version
    except Exception:
        pass
    return "0.0.0"


def parse_resource_identifier(
    raw_val: str,
    domain_config: DomainFusionConfig | None = None,
    default_ns: str = "ENTITY",
) -> Identifier:
    """Parse a raw string, URI, or CURIE into a canonical Identifier in a domain-neutral manner."""
    clean = sanitize_id_value(raw_val, "")
    if not clean:
        return Identifier(namespace=default_ns, value=UNKNOWN_FALLBACK_VALUE)

    # 1. Standard RFC 2141 URN: urn:<nid>:<nss>
    if clean.startswith("urn:"):
        urn_parts = clean.split(":")
        if len(urn_parts) >= 3:
            nid = urn_parts[1].strip().upper()
            nss = ":".join(urn_parts[2:]).strip()
            if nid and nss:
                return Identifier(namespace=nid, value=nss)

    # 2. Standard CURIE: prefix:reference (excluding http/https protocols)
    if ":" in clean and not clean.startswith(("http://", "https://")):
        prefix, ref = clean.split(":", 1)
        prefix = prefix.strip()
        ref = ref.strip()
        if prefix and ref:
            return Identifier(namespace=prefix.upper(), value=ref)

    # 3. If domain_config provided, check against declared entity type namespace prefixes
    if domain_config and domain_config.entity_types:
        clean_lower = clean.lower()
        for et in domain_config.entity_types:
            for prefix in et.namespace_prefixes:
                p_lower = prefix.lower()
                if p_lower in clean_lower:
                    return Identifier(namespace=prefix.upper(), value=clean)

    # 4. Standard HTTP/HTTPS URI: preserve full URI as the identifier value
    if clean.startswith(("http://", "https://")):
        parts = [p for p in re.split(r"[/|#]", clean.rstrip("/")) if p]
        ns = default_ns
        if len(parts) >= 2:
            candidate = parts[-2].upper()
            if candidate.isalnum() and len(candidate) <= 12:
                ns = candidate
        return Identifier(namespace=ns, value=clean)

    return Identifier(namespace=default_ns, value=clean)


class GraphFusionService:
    """Orchestrates end-to-end knowledge graph fusion runs."""

    def __init__(self, parser_registry: ParserRegistry | None = None) -> None:
        self.parser_registry = parser_registry or ParserRegistry()
        self.engine = GenericFusionEngine()

    def parse_content_to_assertions(
        self,
        content: str,
        format_type: str,
        graph_id: Identifier,
        activity_id: Identifier,
        domain_config: DomainFusionConfig | None = None,
    ) -> list[Assertion]:
        """Convert input dataset content into immutable Assertion instances."""
        parsed_at = datetime.now(UTC)
        artifact_id = Identifier(namespace="artifact", value=f"{graph_id.value}_artifact")

        format_aliases = {
            "turtle": MEDIA_TYPE_TURTLE,
            "ttl": MEDIA_TYPE_TURTLE,
            "csv": MEDIA_TYPE_CSV,
            "jsonld": MEDIA_TYPE_JSON_LD,
            "json-ld": MEDIA_TYPE_JSON_LD,
            MEDIA_TYPE_TURTLE: MEDIA_TYPE_TURTLE,
            MEDIA_TYPE_CSV: MEDIA_TYPE_CSV,
            MEDIA_TYPE_JSON_LD: MEDIA_TYPE_JSON_LD,
        }
        media_type = format_aliases.get(format_type.strip().lower())
        if media_type is None:
            raise ValueError(f"Unsupported graph format: {format_type}")

        records = self.parser_registry.parse(
            content.encode("utf-8"),
            artifact_id=artifact_id,
            media_type=media_type,
            parsed_at=parsed_at,
        )

        subj_keys = ("subject", "@id", "id", "source", "from", "src", "entity1", "head", "s")
        pred_keys = (
            "predicate",
            "@type",
            "type",
            "relation",
            "relationship",
            "label",
            "rel",
            "property",
            "p",
        )
        obj_keys = ("object", "target", "to", "dst", "entity2", "tail", "value", "o", "name")

        assertions: list[Assertion] = []
        for idx, rec in enumerate(records, start=1):
            if rec.status == RecordStatus.ERROR:
                continue

            payload = rec.payload or {}

            raw_subj = extract_field(payload, subj_keys)
            raw_pred = extract_field(payload, pred_keys)
            raw_obj = extract_field(payload, obj_keys)
            if not raw_obj and isinstance(payload.get("objects"), list) and payload["objects"]:
                raw_obj = str(payload["objects"][0])

            # Reject records lacking valid subject, predicate, or object
            if not raw_subj or not raw_pred or not raw_obj:
                continue

            subj_val = sanitize_id_value(raw_subj, None)
            pred_val = sanitize_id_value(raw_pred, None)
            obj_val = sanitize_id_value(raw_obj, None)

            if not subj_val or not pred_val or not obj_val:
                continue

            subj_id = parse_resource_identifier(subj_val, domain_config=domain_config)
            obj_id = parse_resource_identifier(obj_val, domain_config=domain_config)

            prov = Provenance(
                assertion_origin=AssertionOrigin.SOURCE,
                agent_id=Identifier(namespace="SYS", value="fusion_agent"),
                activity_id=activity_id,
                asserted_at=parsed_at,
                input_resource_refs=(artifact_id,),
            )
            a = Assertion(
                id=Identifier(namespace="ASSERT", value=f"{graph_id.value}_a_{idx}"),
                subject=subj_id,
                predicate=pred_val,
                object=obj_id,
                provenance=prov,
            )
            assertions.append(a)

        return assertions

    def execute_fusion(
        self,
        request: GraphFusionRequest | None = None,
        *,
        graph_a_id: Identifier | None = None,
        graph_a_assertions: list[Assertion] | None = None,
        graph_b_id: Identifier | None = None,
        graph_b_assertions: list[Assertion] | None = None,
        activity_id: Identifier | None = None,
        conflict_mode: ConflictMode = ConflictMode.CONFLICT_PRESERVE,
        domain_preset: str | None = "general_agnostic",
        domain_config: DomainFusionConfig | str | dict[str, Any] | None = None,
        predicate_authorities: dict[str, str] | None = None,
    ) -> GraphFusionResult:
        """Execute complete 6-stage fusion engine algorithm on assertion streams."""
        if request is not None:
            act_id = Identifier(namespace="activity", value="act_fusion")
            req_a_id = request.graph_a_id or (graph_a_id.value if graph_a_id else "graph_a")
            req_b_id = request.graph_b_id or (graph_b_id.value if graph_b_id else "graph_b")
            g_a_id = Identifier(namespace="release", value=req_a_id)
            g_b_id = Identifier(namespace="release", value=req_b_id)
            hash_a = hashlib.sha256(request.graph_a_content.encode("utf-8")).hexdigest()
            hash_b = hashlib.sha256(request.graph_b_content.encode("utf-8")).hexdigest()
            print(
                f"[Service PHI-Safe Log] Graph A: fmt={request.graph_a_format}, bytes={len(request.graph_a_content)}, sha256={hash_a}"
            )
            print(
                f"[Service PHI-Safe Log] Graph B: fmt={request.graph_b_format}, bytes={len(request.graph_b_content)}, sha256={hash_b}"
            )
            a_assertions = self.parse_content_to_assertions(
                request.graph_a_content, request.graph_a_format, g_a_id, act_id
            )
            b_assertions = self.parse_content_to_assertions(
                request.graph_b_content, request.graph_b_format, g_b_id, act_id
            )
            cfg = request.domain_config or request.domain_preset
            return self.execute_fusion(
                graph_a_id=g_a_id,
                graph_a_assertions=a_assertions,
                graph_b_id=g_b_id,
                graph_b_assertions=b_assertions,
                activity_id=act_id,
                conflict_mode=request.conflict_mode,
                domain_config=cfg,
                domain_preset=request.domain_preset,
            )

        if graph_a_id is None or graph_b_id is None:
            raise ValueError(
                "Explicit graph_a_id and graph_b_id must be provided when executing fusion."
            )

        ga_id = graph_a_id
        gb_id = graph_b_id
        act_id = activity_id or Identifier(namespace="activity", value="act_fusion")
        a_list = graph_a_assertions or []
        b_list = graph_b_assertions or []

        resolved_cfg = resolve_domain_config(domain_config or domain_preset)

        now = datetime.now(UTC)

        def assertion_identity(assertion: Assertion) -> dict[str, str]:
            return {
                "id": assertion.id.canonical,
                "subject": assertion.subject.canonical,
                "predicate": assertion.predicate,
                "object": assertion.object.canonical,
            }

        run_material = json.dumps(
            {
                "graph_a_id": ga_id.canonical,
                "graph_b_id": gb_id.canonical,
                "graph_a_assertions": [assertion_identity(a) for a in a_list],
                "graph_b_assertions": [assertion_identity(a) for a in b_list],
                "domain_config": resolved_cfg.model_dump(mode="json"),
                "conflict_mode": conflict_mode.value,
            },
            sort_keys=True,
            default=str,
        )
        run_hash = f"run_{hashlib.sha256(run_material.encode('utf-8')).hexdigest()[:24]}"

        res = self.engine.fuse(
            graph_a_id=ga_id,
            graph_a_assertions=a_list,
            graph_b_id=gb_id,
            graph_b_assertions=b_list,
            activity_id=act_id,
            conflict_mode=conflict_mode,
            domain_config=resolved_cfg,
            predicate_authorities=predicate_authorities,
        )

        nodes = res.nodes
        edges = res.edges
        merged_count = res.merged_count
        dedup_count = res.dedup_count
        conflict_report = res.conflict_report
        stage_breakdowns = res.stage_breakdowns
        audit_report = res.audit_report
        review_candidates = res.review_candidates

        fusion_run = FusionRun(
            fusion_run_id=Identifier(namespace="fusion_run", value=run_hash),
            graph_a_release_id=ga_id,
            graph_b_release_id=gb_id,
            fusion_policy_id=f"domain_fusion_policy_{resolved_cfg.domain_id}",
            fusion_policy_version=resolved_cfg.fusion_policy_version,
            fusion_policy_digest=compute_policy_digest(resolved_cfg),
            engine_version=get_project_version(),
            candidate_generator_versions=(
                f"exact_id_{resolved_cfg.match_strategy.strategy_version}",
                f"label_similarity_{resolved_cfg.match_strategy.strategy_version}",
                f"structural_{resolved_cfg.match_strategy.strategy_version}",
            ),
            conflict_mode=conflict_mode,
            domain_id=resolved_cfg.domain_id,
            created_at=now,
            result_release_id=Identifier(namespace="release", value=f"rel_fused_{run_hash}"),
        )

        return GraphFusionResult(
            fusion_run=fusion_run,
            total_input_assertions=len(a_list) + len(b_list),
            merged_entity_count=merged_count,
            deduplicated_edge_count=dedup_count,
            derived_assertions_count=len(edges),
            nodes=nodes,
            edges=edges,
            reconciled_assertions=tuple(res.reconciled_assertions),
            conflict_report=conflict_report,
            stage_breakdowns=stage_breakdowns,
            audit_report=audit_report,
            review_candidates=review_candidates,
        )
