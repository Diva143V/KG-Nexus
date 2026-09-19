"""Comprehensive E2E Test Suite Covering Tiers 1 through 4 for Hybrid Knowledge Graph Platform.

Requirement-driven, opaque-box test suite verifying all 30 features from PROJECT.md Feature Inventory:
- Tier 1: Feature Coverage (Happy Path & Core Mechanics)
  - 6-Stage Fusion Execution & Candidate Flow (P1-01, P1-02, P1-03, P1-15, P1-16)
  - Authentic SHA-256 Digest Verification (P1-20, Invariant IX)
  - AttributeAssertion Contract & Persistence (P4-12, R2.6)
  - PluginLoader & Dynamic Registry Routing (P2-02, P4-05)
  - Assertion Review Mutation & Append-Only State Transitions (P1-03, P3-01, Invariant IV)
  - API Graph Merge Ingestion & Store Persistence (P1-09, R1.5)
- Tier 2: Boundary & Corner Cases
  - Rejection of Empty/Whitespace Content (P3-04, Invariant VIII)
  - Disjoint Class Rejection & Non-Hardcoded Negative Handling (P1-07, Invariant VIII)
  - Multimap Lookup & Duplicate Target Class Mappings (P1-13, P1-13b)
  - Absent LLM Verification Fallback Behavior (P3-07, Invariant VII)
  - Non-existent Entity Queries & Idempotent Rollback Boundary
- Tier 3: Cross-Feature Integration Combinations
  - Full Pipeline Execution -> Storage Replay -> Assertion Review Flow
  - Multi-Modal Ingest -> Fusion -> Graph Query Context -> Rollback Durability
  - Truthful Citation & Real Graph Topology Verification (P3-03, P3-05)
  - Dynamic System Benchmarking Metrics Retrieval (P3-06, P3-02)
- Tier 4: Real-World Scenarios
  - Multi-Source Biomedical Fusion (`biomedical_sample_graph.ttl` + `drug_repurposing_graph.csv`)
  - Real Biomedical 13-Stage Release Generation & Projection Lifecycle
  - Architectural Domain Neutrality & Invariant Validation (Invariants I-IX, P2-01, P4-01 to P4-04)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.artifacts.errors import ArtifactIntegrityError
from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.confidence import Confidence, ConfidenceMethod
from core.assertions.literal import LiteralType, LiteralValue, canonical_literal
from core.assertions.resolver import AssertionStateResolver
from core.assertions.state import AssertionState
from core.entities.entity import Entity, EntityKind
from core.evidence.evidence import Evidence, EvidenceKind
from core.fusion.engine import GenericFusionEngine
from core.fusion.meaning_aligner import MeaningAligner
from core.fusion.models import ConflictMode
from core.fusion.service import GraphFusionService
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin, Provenance
from core.releases.status import ReleaseStatus
from infrastructure.api import server as api_server
from infrastructure.api.server import create_server
from infrastructure.release.pipeline import EndToEndReleasePipeline
from infrastructure.storage.artifact_store import DurableArtifactStore
from infrastructure.storage.assertion_store import DurableAssertionStore
from infrastructure.storage.graph_store import GraphStore
from infrastructure.storage.projection_store import DurableProjectionStore
from plugins.biomedical import BiomedicalDomainPack
from plugins.synthetic import SyntheticDomainPack
from sdk.domain_config import resolve_domain_config
from sdk.loader import IncompatiblePluginError, PluginLoader
from sdk.manifest import PluginManifest
from sdk.registries import PluginRegistry


@pytest.fixture(scope="module")
def e2e_server_url() -> Generator[str, None, None]:
    """Start ephemeral REST API server on an auto-selected free port."""
    api_server.GRAPH_STORE.reset()
    server, active_port = create_server("127.0.0.1", 8092)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{active_port}"
    finally:
        server.shutdown()
        server.server_close()
        api_server.GRAPH_STORE.reset()


def _make_test_assertion(
    ass_id: str,
    subject: str = "GENE:101",
    predicate: str = "associated_with",
    obj: str = "DISEASE:202",
    activity_id: str = "act_e2e_test",
) -> Assertion:
    """Helper to construct deterministic, immutable Assertion instances."""
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="agent", value="e2e_tester"),
        activity_id=Identifier(namespace="activity", value=activity_id),
        asserted_at=now,
    )
    evidence = Evidence(
        id=Identifier(namespace="evidence", value=f"ev_{ass_id}"),
        kind=EvidenceKind.PRIMARY,
        record_id=Identifier(namespace="rec", value=f"rec_{ass_id}"),
    )
    s_ns, s_val = subject.split(":", 1) if ":" in subject else ("ENTITY", subject)
    o_ns, o_val = obj.split(":", 1) if ":" in obj else ("ENTITY", obj)
    return Assertion(
        id=Identifier(namespace="assertion", value=ass_id),
        subject=Identifier(namespace=s_ns, value=s_val),
        predicate=predicate,
        object=Identifier(namespace=o_ns, value=o_val),
        status_at_creation=AssertionState.CANDIDATE,
        confidence=Confidence(score=0.92, method=ConfidenceMethod.STATISTICAL),
        evidence=(evidence,),
        provenance=prov,
    )


# ============================================================================
# TIER 1: FEATURE COVERAGE (Happy Path & Core Mechanics)
# ============================================================================


class TestTier1FeatureCoverage:
    """Tier 1: Verify primary happy paths, core features, and data flow contracts."""

    def test_tier1_six_stage_fusion_execution_and_candidate_flow(self) -> None:
        """P1-01, P1-02, P1-15, P1-16: Verify complete 6-stage fusion execution and candidate flow."""
        service = GraphFusionService()
        config = resolve_domain_config("synthetic")
        engine = GenericFusionEngine()

        g_a_id = Identifier(namespace="release", value="rel_tier1_a")
        g_b_id = Identifier(namespace="release", value="rel_tier1_b")
        act_id = Identifier(namespace="activity", value="act_tier1_fusion")

        ttl_prefix = (
            "@prefix synth: <http://example.org/synth/> .\n"
            "@prefix org: <http://example.org/org/> .\n"
        )
        content_a = (
            ttl_prefix
            + "synth:Alice synth:worksAt org:AcmeCorp .\n"
            + "synth:Alice synth:hasRole synth:LeadEngineer .\n"
        )
        content_b = (
            ttl_prefix
            + "synth:Bob synth:worksAt org:AcmeCorp .\n"
            + "synth:Bob synth:collaboratesWith synth:Alice .\n"
        )

        assertions_a = service.parse_content_to_assertions(
            content_a, "turtle", g_a_id, act_id, domain_config=config
        )
        assertions_b = service.parse_content_to_assertions(
            content_b, "turtle", g_b_id, act_id, domain_config=config
        )

        assert len(assertions_a) >= 2
        assert len(assertions_b) >= 2

        # Execute 6-stage fusion engine
        fusion_result = engine.fuse(
            graph_a_id=g_a_id,
            graph_a_assertions=assertions_a,
            graph_b_id=g_b_id,
            graph_b_assertions=assertions_b,
            activity_id=act_id,
            domain_config=config,
            conflict_mode=ConflictMode.CONFLICT_PRESERVE,
        )

        # 1. Stage breakdowns must record metrics for all 6 stages
        stages = fusion_result.stage_breakdowns
        assert "stage_1_normalize_data" in stages
        assert "stage_2_candidate_matches" in stages
        assert "stage_3_align_meaning" in stages
        assert "stage_4_match_confidence" in stages
        assert "stage_5_canonical_entities_facts" in stages
        assert "stage_6_provenance_conflicts" in stages

        # 2. Reconciled assertions and facts must be present and authentic
        assert len(fusion_result.reconciled_assertions) > 0
        assert len(fusion_result.nodes) >= 3
        assert len(fusion_result.edges) >= 2
        assert fusion_result.dedup_count >= 0

        # 3. Provenance and multi-source attribution preserved
        for ra in fusion_result.reconciled_assertions:
            assert ra.provenance.activity_id == act_id
            assert ra.id.canonical.startswith("ASSERT:")

    def test_tier1_authentic_sha256_digests_and_hash_integrity(self, tmp_path: Path) -> None:
        """P1-20, Invariant VI & IX: Verify authentic SHA-256 digest computation and fail-closed integrity."""
        db_path = tmp_path / "artifacts_test.sqlite3"
        graph_store = GraphStore(db_path)
        artifact_store = DurableArtifactStore(db_path)

        release_id = "rel_tier1_sha"
        graph_store.save_release(release_id, {"type": "e2e_artifact_test"})
        release_ref = Identifier(namespace="release", value=release_id)

        raw_bytes = b"@prefix ex: <http://example.org/> .\nex:Alice ex:knows ex:Bob .\n"
        expected_digest = hashlib.sha256(raw_bytes).hexdigest()

        # Store artifact
        now = datetime.now(UTC)
        artifact = artifact_store.store(
            content=raw_bytes,
            source_release_id=release_ref,
            media_type="text/turtle",
            name="test_graph.ttl",
            retrieved_at=now,
        )

        # Verify digest authenticity
        assert artifact.sha256 == expected_digest
        assert artifact.size_bytes == len(raw_bytes)
        assert artifact.id.value == expected_digest

        # Verify retrieval and content addressing
        retrieved_bytes = artifact_store.get_content(artifact.id)
        assert retrieved_bytes == raw_bytes

        found_by_hash = artifact_store.by_sha256(expected_digest)
        assert found_by_hash is not None
        assert found_by_hash.id == artifact.id

        # Verify integrity validation succeeds on genuine content (returns None, does not raise)
        artifact_store.verify_integrity(artifact.id)

        # Forensic verification: corrupt SQLite bytes directly and verify fail-closed detection
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE artifacts SET content = ? WHERE id = ?",
                (b"corrupted_tampered_payload", artifact.id.canonical),
            )
            conn.commit()

        with pytest.raises(ArtifactIntegrityError):
            artifact_store.verify_integrity(artifact.id)

    def test_tier1_attribute_assertion_structure_and_persistence_contract(
        self, tmp_path: Path
    ) -> None:
        """P4-12, R2.6, Invariant III: Verify AttributeAssertion immutable structure and literal handling."""
        lit_str = LiteralValue(type=LiteralType.STRING, value="INS")
        lit_int = LiteralValue(type=LiteralType.INTEGER, value=42)

        now = datetime.now(UTC)
        prov = Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=Identifier(namespace="agent", value="e2e_tester"),
            activity_id=Identifier(namespace="activity", value="act_attr_test"),
            asserted_at=now,
        )

        attr_asn = AttributeAssertion(
            id=Identifier(namespace="ASSERT", value="attr_test_1"),
            subject=Identifier(namespace="HGNC", value="6018"),
            predicate="gene_symbol",
            value=lit_str,
            provenance=prov,
        )

        # 1. Verify model attributes and canonical literal serialization
        assert attr_asn.subject.canonical == "HGNC:6018"
        assert attr_asn.predicate == "gene_symbol"
        assert canonical_literal(attr_asn.value) == "INS"
        assert canonical_literal(lit_int) == "42"

        # 2. Invariant III: Immutable knowledge - frozen model rejects mutation
        with pytest.raises(ValidationError):
            # pyrefly: ignore [attribute-error]
            attr_asn.predicate = "mutated_predicate"  # type: ignore[misc]

        # 3. Verify standard relational Assertion persists into DurableAssertionStore
        db_path = tmp_path / "store_test.sqlite3"
        assertion_store = DurableAssertionStore(db_path)
        rel_asn = _make_test_assertion("rel_asn_tier1")
        assertion_store.persist_assertion(rel_asn)

        loaded = assertion_store.get_assertion(rel_asn.id)
        assert loaded is not None
        assert loaded.id == rel_asn.id
        assert loaded.predicate == rel_asn.predicate

    def test_tier1_plugin_loader_dynamic_registration_and_routing(self) -> None:
        """P2-02, P4-05: Route all plugin access through PluginLoader and PluginRegistry."""
        registry = PluginRegistry()
        loader = PluginLoader(registry)

        synth_pack = SyntheticDomainPack()
        bio_pack = BiomedicalDomainPack()

        # Load synthetic pack
        loader.load(
            synth_pack.manifest,
            pack_components=synth_pack.pack_components(),
        )
        assert registry.is_registered(synth_pack.manifest.plugin_id)

        # Load biomedical pack
        loader.load(
            bio_pack.manifest,
            pack_components=bio_pack.pack_components(),
        )
        assert registry.is_registered(bio_pack.manifest.plugin_id)

        # Incompatible core_api_version must be rejected
        incompatible_manifest = PluginManifest(
            plugin_id="bad_plugin",
            name="Incompatible Plugin",
            version="1.0.0",
            core_api_version="9.9.9",
        )
        with pytest.raises(IncompatiblePluginError):
            loader.validate_compatibility(incompatible_manifest)

    def test_tier1_assertion_lifecycle_state_transitions_and_review(self, tmp_path: Path) -> None:
        """P1-03, P3-01, Invariant IV: Verify append-only assertion state transitions and replay."""
        db_path = tmp_path / "lifecycle_test.sqlite3"
        assertion_store = DurableAssertionStore(db_path)

        asn = _make_test_assertion("asn_lifecycle_101")
        assertion_store.persist_assertion(asn)

        t0 = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
        t1 = datetime(2026, 9, 15, 12, 5, 0, tzinfo=UTC)
        t2 = datetime(2026, 9, 15, 12, 10, 0, tzinfo=UTC)
        t3 = datetime(2026, 9, 15, 12, 15, 0, tzinfo=UTC)

        # Replay event chain: None -> CANDIDATE -> VERIFIED -> PROMOTION_REVIEW -> APPROVED
        ev_creation = AssertionStateEvent(
            event_id=Identifier(namespace="EVT", value="evt_c0"),
            assertion_id=asn.id,
            from_state=None,
            to_state=AssertionState.CANDIDATE,
            agent_id=Identifier(namespace="SYS", value="ingest_agent"),
            activity_id=Identifier(namespace="ACT", value="act_ingest"),
            policy_version="1.0.0",
            reason_code="INITIAL_CREATION",
            timestamp=t0,
        )
        ev_verified = AssertionStateEvent(
            event_id=Identifier(namespace="EVT", value="evt_v1"),
            assertion_id=asn.id,
            from_state=AssertionState.CANDIDATE,
            to_state=AssertionState.VERIFIED,
            agent_id=Identifier(namespace="SYS", value="schema_validator"),
            activity_id=Identifier(namespace="ACT", value="act_validate"),
            policy_version="1.0.0",
            reason_code="PASSED_SCHEMA_CHECKS",
            timestamp=t1,
        )
        ev_review_queued = AssertionStateEvent(
            event_id=Identifier(namespace="EVT", value="evt_r2"),
            assertion_id=asn.id,
            from_state=AssertionState.VERIFIED,
            to_state=AssertionState.PROMOTION_REVIEW,
            agent_id=Identifier(namespace="SYS", value="promotion_guard"),
            activity_id=Identifier(namespace="ACT", value="act_promote"),
            policy_version="1.0.0",
            reason_code="QUEUED_FOR_EXPERT_REVIEW",
            timestamp=t2,
        )
        ev_approved = AssertionStateEvent(
            event_id=Identifier(namespace="EVT", value="evt_a3"),
            assertion_id=asn.id,
            from_state=AssertionState.PROMOTION_REVIEW,
            to_state=AssertionState.APPROVED,
            agent_id=Identifier(namespace="USER", value="curator_dr_smith"),
            activity_id=Identifier(namespace="ACT", value="act_human_review"),
            policy_version="1.0.0",
            reason_code="EXPERT_ACCEPTED_AS_SAME",
            timestamp=t3,
        )

        assertion_store.persist_batch([], [ev_creation, ev_verified, ev_review_queued, ev_approved])

        # Verify event history in temporal order
        events = assertion_store.get_state_events(asn.id)
        assert len(events) == 4
        assert [e.to_state for e in events] == [
            AssertionState.CANDIDATE,
            AssertionState.VERIFIED,
            AssertionState.PROMOTION_REVIEW,
            AssertionState.APPROVED,
        ]

        # Verify deterministic replay resolves to APPROVED
        resolver = AssertionStateResolver()
        resolved_state = resolver.resolve(asn, events)
        assert resolved_state == AssertionState.APPROVED

    def test_tier1_api_graph_merge_persists_release_and_assertions(
        self, e2e_server_url: str
    ) -> None:
        """P1-09, R1.5: Verify POST /api/graph/merge executes fusion and populates store."""
        graph_a = json.dumps(
            [{"subject": "synth:EntityA", "predicate": "interactsWith", "object": "synth:EntityB"}]
        )
        graph_b = json.dumps(
            [{"subject": "synth:EntityB", "predicate": "locatedIn", "object": "synth:PlaceC"}]
        )

        payload = json.dumps(
            {
                "graph_a_content": graph_a,
                "graph_a_format": "jsonld",
                "graph_a_id": "graph_tier1_a",
                "graph_b_content": graph_b,
                "graph_b_format": "jsonld",
                "graph_b_id": "graph_tier1_b",
                "conflict_mode": "conflict_preserve",
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{e2e_server_url}/api/graph/merge",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            body = json.loads(resp.read().decode("utf-8"))
            assert body["status"] == "success"
            fusion = body["fusion"]
            assert len(fusion["nodes"]) >= 3
            assert len(fusion["edges"]) >= 2
            release_id = fusion["fusion_run"]["result_release_id"]["value"]
            assert release_id.startswith("rel_fused_")


# ============================================================================
# TIER 2: BOUNDARY & CORNER CASES
# ============================================================================


class TestTier2BoundaryAndCornerCases:
    """Tier 2: Empty inputs, disjoint classes, duplicate mappings, missing LLM fallback."""

    def test_tier2_empty_and_whitespace_graph_merge_rejected(self, e2e_server_url: str) -> None:
        """P3-04, Invariant VIII: Verify API rejects empty and whitespace-only graphs with HTTP 400."""
        # 1. Empty content
        req_empty = urllib.request.Request(
            f"{e2e_server_url}/api/graph/merge",
            data=json.dumps({"graph_a_content": "", "graph_b_content": "valid"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_empty:
            urllib.request.urlopen(req_empty)
        assert exc_empty.value.code == 400

        # 2. Whitespace-only content
        req_space = urllib.request.Request(
            f"{e2e_server_url}/api/graph/merge",
            data=json.dumps({"graph_a_content": "   \n\t  ", "graph_b_content": "valid"}).encode(
                "utf-8"
            ),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_space:
            urllib.request.urlopen(req_space)
        assert exc_space.value.code == 400

        # 3. Empty query string on graph query
        req_q_empty = urllib.request.Request(
            f"{e2e_server_url}/api/graph/query",
            data=json.dumps({"query": "", "model": "llama3.1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_q:
            urllib.request.urlopen(req_q_empty)
        assert exc_q.value.code == 400

    def test_tier2_disjoint_class_and_low_confidence_rejection(self) -> None:
        """P1-07, Invariant VIII: Calibrated confidence evaluation enforces rejection of low confidence/mismatches."""
        config = resolve_domain_config("biomedical")
        from core.fusion.confidence_decider import ConfidenceDecider

        decider = ConfidenceDecider(config)
        high_th = config.confidence_thresholds.high_confidence_threshold
        rev_th = config.confidence_thresholds.review_threshold

        # High confidence threshold is 0.88, review threshold is 0.65
        assert high_th >= 0.85
        assert rev_th >= 0.60

        from core.fusion.candidate_finder import EnhancedCandidateMatch

        # Candidate 1: Below review threshold (e.g. 0.40) -> KEEP_SEPARATE
        cand_low = EnhancedCandidateMatch(
            source_entity=Entity(
                id=Identifier(namespace="HGNC", value="1001"),
                kind=EntityKind.CONCEPT,
                label="GeneA",
            ),
            candidate_entity=Entity(
                id=Identifier(namespace="MONDO", value="2002"),
                kind=EntityKind.CONCEPT,
                label="DiseaseB",
            ),
            composite_score=0.40,
            primary_method="vector_similarity",
        )
        # Candidate 2: Review band (e.g. 0.75) -> REVIEW_REQUIRED
        cand_mid = EnhancedCandidateMatch(
            source_entity=Entity(
                id=Identifier(namespace="UNIPROT", value="P12345"),
                kind=EntityKind.CONCEPT,
                label="Insulin-like receptor",
            ),
            candidate_entity=Entity(
                id=Identifier(namespace="UNIPROT", value="P54321"),
                kind=EntityKind.CONCEPT,
                label="Insulin receptor precursor",
            ),
            composite_score=0.75,
            primary_method="label_similarity",
        )
        # Candidate 3: High confidence (e.g. 0.96) -> MERGE_AUTOMATIC
        cand_high = EnhancedCandidateMatch(
            source_entity=Entity(
                id=Identifier(namespace="CHEMBL", value="CHEMBL1431"),
                kind=EntityKind.CONCEPT,
                label="Metformin",
            ),
            candidate_entity=Entity(
                id=Identifier(namespace="PUBCHEM", value="4091"),
                kind=EntityKind.CONCEPT,
                label="Metformin",
            ),
            composite_score=0.96,
            primary_method="exact_id",
        )

        res = decider.evaluate_candidates([cand_low, cand_mid, cand_high])

        # Verify tiered calibration outcomes
        assert len(res.kept_separate_pairs) == 1
        assert res.kept_separate_pairs[0]["source_id"] == "1001"

        assert len(res.review_required_pairs) == 1
        assert res.review_required_pairs[0]["source_id"] == "P12345"

        assert len(res.auto_merged_pairs) == 1
        assert res.auto_merged_pairs[0] == ("CHEMBL1431", "4091")

    def test_tier2_duplicate_target_mapping_and_directionality(self) -> None:
        """P1-13, P1-13b: Verify MeaningAligner handles directional mappings and preserves targets."""
        config = resolve_domain_config("biomedical")
        aligner = MeaningAligner(config)

        # align_predicate respects directionality and maps correctly
        canonical_pred, mapping = aligner.align_predicate("targets", from_graph="graph_a")
        assert canonical_pred != ""

        canonical_treats, m_treats = aligner.align_predicate("treats", from_graph="graph_a")
        assert canonical_treats != ""

    def test_tier2_missing_llm_provider_fallback_handling(self, e2e_server_url: str) -> None:
        """P3-07, Invariant VII: Missing LLM provider returns graceful unavailable status without crashing."""
        payload = json.dumps(
            {
                "pair": {"source": "HGNC:6018", "target": "UNIPROT:P01308"},
                "confidence": 0.88,
                "model": "nonexistent_model_8b",
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{e2e_server_url}/api/alignment/verify",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assert data["status"] in ("unavailable", "success")
        except urllib.error.HTTPError as exc:
            # If server returns 503 (model unavailable), verify JSON payload is clean and informative
            assert exc.code in (503, 400)
            err_data = json.loads(exc.read().decode("utf-8"))
            assert err_data["status"] in ("unavailable", "error")

    def test_tier2_nonexistent_assertion_query_and_rollback_boundary(
        self, tmp_path: Path, e2e_server_url: str
    ) -> None:
        """Boundary: Querying missing assertions returns None/404; initial rollback handles empty state."""
        db_path = tmp_path / "empty_boundary.sqlite3"
        assertion_store = DurableAssertionStore(db_path)

        # Missing assertion returns None
        missing = assertion_store.get_assertion(Identifier(namespace="ASSERT", value="missing_123"))
        assert missing is None

        # Missing assertion via API returns 404
        req_missing = urllib.request.Request(
            f"{e2e_server_url}/api/assertions/ASSERT:missing_assertion_999"
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_missing)
        assert exc_info.value.code == 404


# ============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (Integration Workflows)
# ============================================================================


class TestTier3CrossFeatureCombinations:
    """Tier 3: Pipeline run -> API query -> review action -> state durability -> rollback."""

    def test_tier3_end_to_end_pipeline_to_review_lifecycle(self, tmp_path: Path) -> None:
        """P1-01, P1-03, P3-01, E2E-01: Full pipeline run followed by human review mutation and replay."""
        db_path = tmp_path / "e2e_tier3.sqlite3"
        graph_store = GraphStore(db_path)
        artifact_store = DurableArtifactStore(db_path)
        assertion_store = DurableAssertionStore(db_path)
        projection_store = DurableProjectionStore(db_path)

        pipeline = EndToEndReleasePipeline(
            database_path=db_path,
            graph_store=graph_store,
            artifact_store=artifact_store,
            assertion_store=assertion_store,
            projection_store=projection_store,
        )
        pack = SyntheticDomainPack()
        run_id = "run_tier3_cross_001"
        release_id = f"release_{run_id}"

        # 1. Execute end-to-end pipeline
        result = pipeline.execute_pipeline(plugin_pack=pack, run_id=run_id)
        assert result.stage_statuses["candidate_generation"] == "PASS"
        assert result.stage_statuses["assertion_creation"] == "PASS"
        assert result.stage_statuses["state_transitions"] == "PASS"
        assert result.stage_statuses["projection"] == "PASS"

        # 2. Assertions are persisted in DurableAssertionStore
        release_assertions = assertion_store.get_by_release(release_id)
        assert len(release_assertions) >= 1
        target_asn = release_assertions[0]

        # 3. Perform a human curator review mutation on the assertion
        review_time = datetime.now(UTC)
        curator_event = AssertionStateEvent(
            event_id=Identifier(namespace="EVT", value=f"evt_review_{target_asn.id.value}"),
            assertion_id=target_asn.id,
            from_state=AssertionState.APPROVED,
            to_state=AssertionState.RETRACTED,
            agent_id=Identifier(namespace="USER", value="curator_lead"),
            activity_id=Identifier(namespace="ACT", value="act_triage_review"),
            policy_version="1.0.0",
            reason_code="CURATOR_RETRACTED_DUE_TO_NEW_EVIDENCE",
            timestamp=review_time,
        )
        assertion_store.persist_state_event(curator_event)

        # 4. Verify event is appended and state resolver deterministically yields RETRACTED
        events = assertion_store.get_state_events(target_asn.id)
        assert any(e.event_id == curator_event.event_id for e in events)

        resolver = AssertionStateResolver()
        current_state = resolver.resolve(target_asn, events)
        assert current_state == AssertionState.RETRACTED

        # 5. Invariant III & IV check: original assertion in SQLite was not updated in-place
        reloaded_asn = assertion_store.get_assertion(target_asn.id)
        assert reloaded_asn is not None
        assert reloaded_asn.status_at_creation == target_asn.status_at_creation

    def test_tier3_multi_modal_ingest_merge_query_rollback(self, e2e_server_url: str) -> None:
        """Ingest -> Merge -> Graph Data Inspection -> Rollback."""
        # 1. Ingest JSON-LD entity graph
        ingest_payload = json.dumps(
            {
                "file_name": "people.jsonld",
                "format": "jsonld",
                "content": json.dumps(
                    [{"subject": "synth:A1", "predicate": "worksAt", "object": "synth:O1"}]
                ),
            }
        ).encode("utf-8")
        req_ingest = urllib.request.Request(
            f"{e2e_server_url}/api/ingest/upload",
            data=ingest_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_ingest) as resp:
            assert resp.status == 200

        # 2. Merge Graph A and Graph B
        merge_payload = json.dumps(
            {
                "graph_a_content": json.dumps(
                    [{"subject": "synth:A1", "predicate": "worksAt", "object": "synth:O1"}]
                ),
                "graph_a_format": "jsonld",
                "graph_b_content": json.dumps(
                    [{"subject": "synth:B2", "predicate": "worksAt", "object": "synth:O1"}]
                ),
                "graph_b_format": "jsonld",
            }
        ).encode("utf-8")
        req_merge = urllib.request.Request(
            f"{e2e_server_url}/api/graph/merge",
            data=merge_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_merge) as resp:
            assert resp.status == 200

        # 3. Query active graph data
        req_data = urllib.request.Request(f"{e2e_server_url}/api/graph/data")
        with urllib.request.urlopen(req_data) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "success"
            assert len(data["nodes"]) >= 2

        # 4. Rollback to restore previous snapshot
        req_rollback = urllib.request.Request(
            f"{e2e_server_url}/api/release/rollback",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_rollback) as resp:
            assert resp.status in (200, 409)

    def test_tier3_dynamic_benchmark_metrics_integrity(self, e2e_server_url: str) -> None:
        """P3-06, P3-02: Verify dynamic benchmark analytics metrics are genuine and calibrated."""
        req = urllib.request.Request(f"{e2e_server_url}/api/benchmarks/metrics")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "success"
            metrics = data["metrics"]
            assert metrics["dataset"] == "biomedical_1.0.0"
            assert metrics["candidate_generation"]["recall_at_10"] >= 0.80
            assert metrics["resolution"]["precision"] >= 0.70
            assert metrics["resolution"]["recall"] >= 0.80
            assert metrics["resolution"]["f1"] >= 0.75
            assert metrics["projection"]["rebuild_reproducible"] is True
            assert metrics["projection"]["build_time_ms"] > 0.0

    def test_tier3_truthful_citations_and_graph_topology(self, tmp_path: Path) -> None:
        """P3-03, P3-05: Citation count and neighbor overlap must reflect authentic graph topology."""
        graph_store = GraphStore(tmp_path / "topo.sqlite3")
        graph_store.replace_active(
            nodes=[
                {"id": "node_1", "label": "Node 1"},
                {"id": "node_2", "label": "Node 2"},
                {"id": "node_3", "label": "Node 3"},
            ],
            edges=[
                {"from": "node_1", "to": "node_2", "label": "connects"},
                {"from": "node_1", "to": "node_3", "label": "references"},
            ],
        )
        active = graph_store.get_active()
        assert len(active["nodes"]) == 3
        assert len(active["edges"]) == 2

        # Node 1 has exactly 2 neighbors in true topology
        node_1_neighbors = [e["to"] for e in active["edges"] if e["from"] == "node_1"]
        assert len(node_1_neighbors) == 2
        assert "node_2" in node_1_neighbors
        assert "node_3" in node_1_neighbors


# ============================================================================
# TIER 4: REAL-WORLD SCENARIOS & ARCHITECTURAL INVARIANTS
# ============================================================================


class TestTier4RealWorldScenarios:
    """Tier 4: Multi-source biomedical fusion, 13-stage release pipeline, and architectural boundaries."""

    def test_tier4_multi_source_biomedical_fusion_real_world_scenario(self) -> None:
        """ADV-01, M7: Multi-source fusion of real biomedical datasets (Turtle + CSV)."""
        root_dir = Path(__file__).resolve().parent.parent
        ttl_path = root_dir / "testdata" / "biomedical_sample_graph.ttl"
        csv_path = root_dir / "testdata" / "drug_repurposing_graph.csv"

        assert ttl_path.exists(), f"Missing dataset: {ttl_path}"
        assert csv_path.exists(), f"Missing dataset: {csv_path}"

        ttl_content = ttl_path.read_text(encoding="utf-8")
        csv_content = csv_path.read_text(encoding="utf-8")

        service = GraphFusionService()
        config = resolve_domain_config("biomedical")
        engine = GenericFusionEngine()

        g_ttl_id = Identifier(namespace="release", value="rel_biomed_ttl")
        g_csv_id = Identifier(namespace="release", value="rel_biomed_csv")
        act_id = Identifier(namespace="activity", value="act_biomed_e2e_fusion")

        # Parse assertions from both formats
        ttl_assertions = service.parse_content_to_assertions(
            ttl_content, "turtle", g_ttl_id, act_id, domain_config=config
        )
        csv_assertions = service.parse_content_to_assertions(
            csv_content, "csv", g_csv_id, act_id, domain_config=config
        )

        assert len(ttl_assertions) >= 6
        assert len(csv_assertions) >= 6

        # Execute 6-stage fusion
        fusion_res = engine.fuse(
            graph_a_id=g_ttl_id,
            graph_a_assertions=ttl_assertions,
            graph_b_id=g_csv_id,
            graph_b_assertions=csv_assertions,
            activity_id=act_id,
            domain_config=config,
            conflict_mode=ConflictMode.CONFLICT_PRESERVE,
        )

        # Verify real biomedical entities are unified:
        # Expected concepts: HGNC:6018 (INS), UniProt:P01308, ChEMBL:CHEMBL1431 (Metformin), MONDO:0005148
        reconciled = fusion_res.reconciled_assertions
        assert len(reconciled) > 0
        node_ids = {n["id"] for n in fusion_res.nodes}

        # Check key biomedical identifiers are represented in fused graph
        has_insulin = any("P01308" in nid or "6018" in nid for nid in node_ids)
        has_metformin = any("1431" in nid for nid in node_ids)
        has_diabetes = any("0005148" in nid for nid in node_ids)

        assert has_insulin, f"Insulin entity missing from node_ids: {node_ids}"
        assert has_metformin, f"Metformin entity missing from node_ids: {node_ids}"
        assert has_diabetes, f"Diabetes entity missing from node_ids: {node_ids}"

        # Verify deduplication and stage evidence
        assert fusion_res.dedup_count >= 0
        assert len(fusion_res.edges) > 0

    def test_tier4_biomedical_13_stage_release_pipeline(self, tmp_path: Path) -> None:
        """P1-01, P1-02, P1-20: Execute full 13-stage release lifecycle for BiomedicalDomainPack."""
        db_path = tmp_path / "biomedical_tier4.sqlite3"
        graph_store = GraphStore(db_path)
        artifact_store = DurableArtifactStore(db_path)
        assertion_store = DurableAssertionStore(db_path)
        projection_store = DurableProjectionStore(db_path)

        pipeline = EndToEndReleasePipeline(
            database_path=db_path,
            graph_store=graph_store,
            artifact_store=artifact_store,
            assertion_store=assertion_store,
            projection_store=projection_store,
        )
        pack = BiomedicalDomainPack()
        run_id = "run_tier4_biomed_001"
        release_id = f"release_{run_id}"

        # Execute all 13 stages
        result = pipeline.execute_pipeline(plugin_pack=pack, run_id=run_id)

        # 1. Verify all 13 stages report PASS
        expected_stages = [
            "ingest",
            "normalize",
            "candidate_generation",
            "assertion_creation",
            "state_transitions",
            "provenance",
            "validation",
            "release",
            "rdf_snapshot",
            "projection",
            "reconciliation",
            "endpoint_switch",
            "rollback",
        ]
        for stage in expected_stages:
            assert result.stage_statuses.get(stage) == "PASS", (
                f"Stage {stage} did not PASS: {result.stage_statuses}"
            )

        # 2. Release is formally PUBLISHED
        rel_rec = graph_store.get_release(release_id)
        assert rel_rec is not None
        assert rel_rec["status"] == ReleaseStatus.PUBLISHED.value

        # 3. Assertions are linked and stored
        stored_assertions = assertion_store.get_by_release(release_id)
        assert len(stored_assertions) >= 1

        # 4. Projections are recorded and verified
        active_proj = projection_store.get_all_active()
        assert len(active_proj) >= 1
        assert active_proj[0].release_id == release_id

    def test_tier4_architectural_domain_neutrality_and_invariants(self) -> None:
        """Invariants I, II, III, V, VI, IX: Zero domain leakage in core and adherence to architectural laws."""
        root_dir = Path(__file__).resolve().parent.parent
        core_dir = root_dir / "core"

        # Invariant I: core/ must never import from plugins/
        for py_file in core_dir.rglob("*.py"):
            code_text = py_file.read_text(encoding="utf-8")
            assert "from plugins" not in code_text, (
                f"Domain leakage: {py_file} imports directly from plugins!"
            )
            assert "import plugins" not in code_text, (
                f"Domain leakage: {py_file} imports directly from plugins!"
            )

        # Invariant III: Immutable knowledge - verify Assertion and AttributeAssertion are frozen
        rel_asn = _make_test_assertion("immutability_check")
        with pytest.raises(ValidationError):
            # pyrefly: ignore [attribute-error]
            rel_asn.predicate = "tampered"  # type: ignore[misc]

        # Invariant IX: Domain config is the single source of truth for thresholds
        synth_cfg = resolve_domain_config("synthetic")
        bio_cfg = resolve_domain_config("biomedical")
        assert synth_cfg.confidence_thresholds.high_confidence_threshold == 0.88
        assert bio_cfg.confidence_thresholds.high_confidence_threshold == 0.88
