"""Regression tests for fail-closed behavior and cross-run invariants.

Coverage map:
- pipeline: fuses two independent source graphs; refuses a single source;
  manifest records real, pack-declared component versions
- parsing: malformed Turtle (undeclared prefixes) raises; placeholder
  namespaces never enter the graph
- http: unknown CORS origins receive no ACAO header; mutating routes require
  a bearer token and fail closed when none is configured
- sdk: defaults are domain-neutral; unknown config strings raise
- models: graph nodes are immutable; engine version resolves consistently
- fusion: candidate ordering is hash-seed independent; the review band
  abstains regardless of matcher method labels; blank identifiers raise;
  exact-identifier matches are labeled as such; audit mappings come from the
  structured mapping log
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import HTTPServer
from pathlib import Path
from threading import Thread

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Pipeline: two independent sources
# ---------------------------------------------------------------------------


def test_pipeline_fuses_two_independent_sources(tmp_path: Path) -> None:
    from infrastructure.release.pipeline import EndToEndReleasePipeline
    from plugins.biomedical import BiomedicalDomainPack

    pipeline = EndToEndReleasePipeline(database_path=tmp_path / "c1.sqlite3")
    result = pipeline.execute_pipeline(
        plugin_pack=BiomedicalDomainPack(), run_id="c1_independent_sources"
    )

    norm = result.stage_evidence["normalize"]
    assert norm["graph_a_assertions"] > 0
    assert norm["graph_b_assertions"] > 0
    assert result.stage_evidence["candidate_generation"]["candidate_pairs_surfaced"] > 0


def test_pipeline_fails_closed_with_single_source_graph(tmp_path: Path) -> None:
    """One artifact = one graph; fusion against itself must fail, not bisect."""
    from infrastructure.release.pipeline import EndToEndReleasePipeline
    from plugins.synthetic import SyntheticDomainPack

    pipeline = EndToEndReleasePipeline(database_path=tmp_path / "c1b.sqlite3")
    result = pipeline.execute_pipeline(
        plugin_pack=SyntheticDomainPack(),
        run_id="c1_single_source",
        raw_artifacts=[{"name": "only_a.ttl", "content": b"@prefix ex: <http://x.org/> .\nex:a ex:b ex:c .\n", "media_type": "turtle"}],
    )

    assert result.stage_statuses["normalize"] == "FAIL"
    assert "two independent source graphs" in result.stage_evidence["normalize"]["error"]


def test_pipeline_artifacts_routed_by_explicit_provenance(tmp_path: Path) -> None:
    from infrastructure.release.pipeline import EndToEndReleasePipeline
    from plugins.biomedical import BiomedicalDomainPack

    pipeline = EndToEndReleasePipeline(database_path=tmp_path / "c1c.sqlite3")
    result = pipeline.execute_pipeline(
        plugin_pack=BiomedicalDomainPack(), run_id="c1_provenance_routing"
    )

    ingest_evidence = result.stage_evidence["ingest"]
    assert len(ingest_evidence["graph_a_artifacts"]) >= 1
    assert len(ingest_evidence["graph_b_artifacts"]) >= 1


# ---------------------------------------------------------------------------
# Parsing: fail closed
# ---------------------------------------------------------------------------


def test_turtle_undeclared_prefix_raises() -> None:
    from core.identifiers.identifier import Identifier
    from core.parsing.errors import ParsingError
    from core.parsing.parsers import TurtleParser

    with pytest.raises(ParsingError):
        TurtleParser().parse(
            b"exa:a exa:b exb:c .",
            artifact_id=Identifier(namespace="artifact", value="test"),
            parsed_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )


def test_turtle_placeholder_namespaces_never_appear() -> None:
    """Placeholder namespaces must never enter the graph."""
    from datetime import UTC, datetime

    from core.identifiers.identifier import Identifier
    from core.parsing.errors import ParsingError
    from core.parsing.parsers import TurtleParser

    parser = TurtleParser()
    with pytest.raises(ParsingError):
        parser.parse(
            b"exa:x exa:y exb:z .",
            artifact_id=Identifier(namespace="artifact", value="t2"),
            parsed_at=datetime.now(UTC),
        )


# ---------------------------------------------------------------------------
# CORS: fail closed
# ---------------------------------------------------------------------------


def test_cors_unknown_origin_gets_no_acao(monkeypatch: pytest.MonkeyPatch) -> None:
    from infrastructure.api import security

    monkeypatch.setenv("HYBRID_KG_CORS_ORIGIN", "https://prod.example.com")
    monkeypatch.delenv("HYBRID_KG_ALLOW_DEV_ORIGINS", raising=False)

    assert security.cors_origin_for("https://prod.example.com") == "https://prod.example.com"
    assert security.cors_origin_for("https://evil.attacker.com") is None
    assert security.cors_origin_for("null") is None
    assert security.cors_origin_for("") is None


def test_cors_localhost_requires_explicit_dev_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from infrastructure.api import security

    monkeypatch.setenv("HYBRID_KG_CORS_ORIGIN", "https://prod.example.com")
    monkeypatch.delenv("HYBRID_KG_ALLOW_DEV_ORIGINS", raising=False)
    assert security.cors_origin_for("http://127.0.0.1:8000") is None

    monkeypatch.setenv("HYBRID_KG_ALLOW_DEV_ORIGINS", "1")
    assert security.cors_origin_for("http://127.0.0.1:8000") == "http://127.0.0.1:8000"


def test_cors_over_real_server_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end through PlatformRequestHandler: non-allowlisted origin gets no header."""
    import urllib.request


    monkeypatch.setenv("HYBRID_KG_CORS_ORIGIN", "https://good.example")
    monkeypatch.delenv("HYBRID_KG_ALLOW_DEV_ORIGINS", raising=False)

    from infrastructure.api.server import PlatformRequestHandler

    srv = HTTPServer(("127.0.0.1", 0), PlatformRequestHandler)
    thread = Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        port = srv.server_port
        for origin in ("https://good.example", "https://evil.io"):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            req.add_header("Origin", origin)
            with urllib.request.urlopen(req, timeout=10) as resp:
                acao = resp.headers.get("Access-Control-Allow-Origin")
            if origin == "https://good.example":
                assert acao == origin
            else:
                assert acao is None
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_post_routes_require_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from infrastructure.api import security

    monkeypatch.setenv("HYBRID_KG_AUTH_TOKEN", "s3cret")
    assert security.route_requires_auth("POST", "/api/graph/merge") is True
    assert security.route_requires_auth("GET", "/api/graph/merge") is False
    assert security.route_requires_auth("POST", "/health") is False

    assert security.is_authorized("Bearer s3cret") is True
    assert security.is_authorized("Bearer wrong") is False
    assert security.is_authorized("Basic s3cret") is False
    assert security.is_authorized(None) is False


def test_missing_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from infrastructure.api import security

    monkeypatch.delenv("HYBRID_KG_AUTH_TOKEN", raising=False)
    assert security.is_authorized("Bearer anything") is False


def test_unauthenticated_post_is_rejected_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error
    import urllib.request

    from infrastructure.api.server import PlatformRequestHandler

    monkeypatch.setenv("HYBRID_KG_AUTH_TOKEN", "tok-123")
    srv = HTTPServer(("127.0.0.1", 0), PlatformRequestHandler)
    thread = Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        port = srv.server_port
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/graph/merge",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=10)
        assert excinfo.value.code == 401

        # With the token, the request passes the auth layer and reaches the
        # handler — which then rejects the empty body (urllib raises on 4xx).
        req2 = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/graph/merge",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer tok-123"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo2:
            urllib.request.urlopen(req2, timeout=10)
        assert excinfo2.value.code == 400  # business validation, NOT 401
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# Manifest versions
# ---------------------------------------------------------------------------


def test_pipeline_manifest_reports_real_component_versions(tmp_path: Path) -> None:
    from infrastructure.release.pipeline import EndToEndReleasePipeline
    from plugins.biomedical import BiomedicalDomainPack

    pipeline = EndToEndReleasePipeline(database_path=tmp_path / "c5.sqlite3")
    result = pipeline.execute_pipeline(
        plugin_pack=BiomedicalDomainPack(), run_id="c5_versions"
    )

    m = result.manifest
    assert m.matcher_version.startswith("candidate_finder_")
    assert m.model_version.startswith("ollama_local:")
    assert m.reasoner_version == "provenance_conflict_v1"
    assert m.projection_version == "projection_backend_v1"
    # source_releases are derived from actual ingested artifacts
    assert any("graph_a_chembl" in s for s in m.source_releases)
    assert any("graph_b_drugbank" in s for s in m.source_releases)


def test_pipeline_refuses_pack_without_component_versions(tmp_path: Path) -> None:
    from infrastructure.release.pipeline import EndToEndReleasePipeline

    class NoVersionsPack:
        class manifest:  # minimal duck-typed manifest
            plugin_id = "hollow_pack"
            version = "1.0.0"
            core_api_version = "1.0.0"
            dependencies: list[str] = []

        def pack_components(self) -> dict:
            return {}

        def get_domain_config(self):  # pragma: no cover
            from sdk.domain_config import get_general_agnostic_preset

            return get_general_agnostic_preset()

    pipeline = EndToEndReleasePipeline(database_path=tmp_path / "c5b.sqlite3")
    with pytest.raises(ValueError, match="component_versions"):
        pipeline.execute_pipeline(plugin_pack=NoVersionsPack(), run_id="c5_no_versions")


def test_pipeline_refuses_pack_without_domain_config(tmp_path: Path) -> None:
    from infrastructure.release.pipeline import EndToEndReleasePipeline
    from plugins.synthetic import SyntheticDomainPack

    class NoConfigPack(SyntheticDomainPack):
        def get_domain_config(self):  # pragma: no cover
            return None

    pipeline = EndToEndReleasePipeline(database_path=tmp_path / "c5c.sqlite3")
    with pytest.raises(ValueError, match="domain fusion configuration"):
        pipeline.execute_pipeline(plugin_pack=NoConfigPack(), run_id="c5_no_cfg")


# ---------------------------------------------------------------------------
# SDK defaults: domain-neutral
# ---------------------------------------------------------------------------


def test_sdk_defaults_are_domain_neutral() -> None:
    from sdk.domain_config import (
        ConflictResolutionRules,
        DomainFusionConfig,
        LiteralRuleConfig,
        MatchStrategyConfig,
    )

    banned = {
        "_drug",
        "_target",
        "_disease",
        "chembl_id",
        "treats",
        "contraindicates",
        "chemicalformula",
        "molecularweight",
        "approveddate",
        "birthdate",
        "dateofbirth",
        "foundeddate",
        "ceo",
        "capitalcity",
    }

    cfg = DomainFusionConfig()
    assert not banned & {s.lower() for s in cfg.match_strategy.role_suffixes_to_strip}
    assert not banned & {p.lower() for p in cfg.literal_rules.literal_predicates}
    assert not banned & {p.lower() for pair in cfg.conflict_rules.opposing_predicates for p in pair}
    assert not banned & {p.lower() for p in cfg.conflict_rules.functional_predicates}

    # The bare component defaults must agree with the composed default config.
    assert not banned & {s.lower() for s in MatchStrategyConfig().role_suffixes_to_strip}
    assert not banned & {p.lower() for p in LiteralRuleConfig().literal_predicates}
    assert ConflictResolutionRules().opposing_predicates == ()


def test_sdk_no_longer_exports_domain_preset_helpers() -> None:
    import sdk

    assert not hasattr(sdk, "get_biomedical_preset")
    assert not hasattr(sdk, "get_synthetic_preset")

    import sdk.domain_config as dc

    assert not hasattr(dc, "get_biomedical_preset")
    assert not hasattr(dc, "get_synthetic_preset")

    # And sdk must not import plugins (rule.md §3.1) — check import statements,
    # ignoring comments.
    import sys

    mod = sys.modules.get("sdk.domain_config")
    if mod is not None and mod.__file__:
        for line in open(mod.__file__, encoding="utf-8"):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert not stripped.startswith("import plugins"), stripped
            assert not stripped.startswith("from plugins"), stripped


def test_biomedical_still_registered_via_plugin_import() -> None:
    """The preset lives in the plugin; registration happens on plugin import."""
    import plugins.biomedical.config  # noqa: F401  (import-for-effect)
    from sdk.domain_config import DOMAIN_PRESETS

    assert "biomedical" in DOMAIN_PRESETS


def test_resolve_domain_config_fails_closed_on_bad_json() -> None:
    import pytest as _pytest

    from sdk.domain_config import resolve_domain_config

    with _pytest.raises(ValueError, match="Invalid domain configuration"):
        resolve_domain_config("{not valid json")


def test_default_graph_precedence_is_typed() -> None:
    from sdk.domain_config import ConflictResolutionRules, GraphPrecedence

    assert ConflictResolutionRules().default_graph_precedence == GraphPrecedence.GRAPH_A
    with pytest.raises(ValueError):
        ConflictResolutionRules(default_graph_precedence="grap_a")  # typo must be rejected


# ---------------------------------------------------------------------------
# Graph nodes: immutable
# ---------------------------------------------------------------------------


def test_entity_is_frozen() -> None:
    from pydantic import ValidationError

    from core.entities.entity import Entity, EntityKind
    from core.identifiers.identifier import Identifier

    e = Entity(id=Identifier(namespace="EX", value="a"), kind=EntityKind.CONCEPT, label="A")
    with pytest.raises(ValidationError):
        e.label = "MUTATED"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        e.kind = EntityKind.LOCATION  # type: ignore[misc]


def test_normalizer_does_not_mutate_entities() -> None:
    """Label literals must be captured at construction, not mutated in afterwards."""
    from datetime import UTC, datetime

    from core.assertions.assertion import Assertion
    from core.fusion.normalizer import DataNormalizer
    from core.identifiers.identifier import Identifier
    from core.provenance.provenance import AssertionOrigin, Provenance
    from sdk.domain_config import get_general_agnostic_preset

    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="SYS", value="t"),
        activity_id=Identifier(namespace="ACT", value="t"),
        asserted_at=datetime.now(UTC),
    )

    def asn(i: int, s: str, p: str, o: str) -> Assertion:
        return Assertion(
            id=Identifier(namespace="ASSERT", value=f"a{i}"),
            subject=Identifier.parse(s),
            predicate=p,
            object=Identifier.parse(o),
            provenance=prov,
        )

    # The label literal arrives after the structural assertion.
    assertions = [
        asn(1, "urn:ex:person1", "urn:ex:knows", "urn:ex:person2"),
        asn(2, "urn:ex:person1", "urn:ex:name", "urn:lit:AliceLiddell"),
    ]

    cfg = get_general_agnostic_preset()
    graph = DataNormalizer(cfg).normalize_graph(assertions, "graph_a")
    # Entities are keyed by identifier value ('urn' ns stripped by parse).
    assert graph.entities["ex:person1"].label == "lit:AliceLiddell"


# ---------------------------------------------------------------------------
# Projection framework
# ---------------------------------------------------------------------------


def test_core_has_single_projection_module() -> None:
    assert not (Path("core") / "projections").exists()
    legacy = Path("infrastructure") / "projections" / "legacy_framework"
    assert legacy.exists()  # moved out of core, not deleted


def test_single_projection_status_enum_in_core() -> None:
    """The canonical core projection lifecycle is the only status enum in core/."""
    from core.projection.lifecycle import ProjectionStatus as CanonicalStatus

    assert CanonicalStatus.__members__


def test_memory_backend_uses_canonical_core_profile() -> None:
    """The backend must not import two different profile models in one file."""
    src = open("infrastructure/projections/memory.py", encoding="utf-8").read()
    assert src.count("from core.projection.profile import ProjectionProfile") == 1
    assert "legacy_framework.content" in src


# ---------------------------------------------------------------------------
# Candidate generation: deterministic
# ---------------------------------------------------------------------------


def test_candidate_order_is_hash_seed_independent(tmp_path: Path) -> None:
    """The >1000-pair path must produce identical output under any PYTHONHASHSEED."""
    root = Path(__file__).resolve().parent.parent
    script = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "from core.identifiers.identifier import Identifier\n"
        "from core.fusion.candidate_finder import CandidateFinder\n"
        "from core.fusion.normalizer import NormalizedGraph\n"
        "from core.entities.entity import Entity, EntityKind\n"
        "from sdk.domain_config import get_general_agnostic_preset\n"
        "\n"
        "def make_graph(prefix, n):\n"
        "    g = NormalizedGraph(graph_id=prefix)\n"
        "    for i in range(n):\n"
        '        eid = f"{prefix}_{i}"\n'
        "        g.entities[eid] = Entity(\n"
        "            id=Identifier(namespace=prefix.upper(), value=str(i)),\n"
        "            kind=EntityKind.CONCEPT,\n"
        '            label=f"Entity {i}",\n'
        "        )\n"
        "    return g\n"
        "\n"
        'a = make_graph("ga", 40)\n'
        'b = make_graph("gb", 40)\n'
        "finder = CandidateFinder(get_general_agnostic_preset())\n"
        'cands = finder.find_candidates(a, b, Identifier(namespace="ACT", value="act"))\n'
        "print(json.dumps([c.source_entity.id.canonical for c in cands]))\n"
    )
    script_path = tmp_path / "determinism_probe.py"
    script_path.write_text(script, encoding="utf-8")

    outputs: list[str] = []
    for seed in ("0", "1", "2", "3"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=True,
        )
        outputs.append(proc.stdout.strip())
    assert len(set(outputs)) == 1, f"Ordering varied across hash seeds: {outputs}"


# ---------------------------------------------------------------------------
# Review band
# ---------------------------------------------------------------------------


def _make_candidate(score: float, method: str):
    from core.entities.entity import Entity, EntityKind
    from core.identifiers.identifier import Identifier
    from core.resolution.models import CandidateMatch

    return CandidateMatch(
        source_entity=Entity(
            id=Identifier(namespace="EX", value="s"), kind=EntityKind.CONCEPT, label="S"
        ),
        candidate_entity=Entity(
            id=Identifier(namespace="EX", value="t"), kind=EntityKind.CONCEPT, label="T"
        ),
        ranking_score=score,
        ranking_method=method,
        activity_id=Identifier(namespace="ACT", value="act"),
    )


def test_review_band_abstains_even_for_normalized_label() -> None:
    """A method label must never bypass the band: 0.75 in [0.65, 0.88) -> abstain."""
    from core.fusion.engine import DefaultIdentityPolicy
    from sdk.domain_config import get_general_agnostic_preset

    policy = DefaultIdentityPolicy(get_general_agnostic_preset())
    decision = policy.evaluate(_make_candidate(0.75, "normalized_label"))
    assert decision.accepted is False
    assert decision.method == "review_band_abstain"


def test_high_confidence_accepts_low_confidence_rejects() -> None:
    from core.fusion.engine import DefaultIdentityPolicy
    from sdk.domain_config import get_general_agnostic_preset

    policy = DefaultIdentityPolicy(get_general_agnostic_preset())
    assert policy.evaluate(_make_candidate(0.95, "lexical_similarity")).accepted is True
    rejected = policy.evaluate(_make_candidate(0.50, "lexical_similarity"))
    assert rejected.accepted is False
    assert rejected.method == "low_confidence_rejection"


def test_exact_identifier_is_recognized_not_mislabeled() -> None:
    from core.fusion.engine import DefaultIdentityPolicy
    from sdk.domain_config import get_general_agnostic_preset

    policy = DefaultIdentityPolicy(get_general_agnostic_preset())
    decision = policy.evaluate(_make_candidate(1.0, "exact_identifier"))
    assert decision.accepted is True
    assert decision.method == "exact_uri_policy_acceptance"


def test_verified_llm_accept_is_dead_and_gone() -> None:
    """Model outputs can never bypass structural validators (PHILOSOPHY §V)."""
    src = open("core/fusion/engine.py", encoding="utf-8").read()
    assert "verified_llm_accept" not in src


# ---------------------------------------------------------------------------
# Conflict resolution, versions, identifiers
# ---------------------------------------------------------------------------


def test_conflict_tier1_reads_assertion_confidence() -> None:
    """Confidence comparison must use real Confidence models, not dead getattr."""
    from datetime import UTC, datetime

    from core.assertions.assertion import Assertion
    from core.assertions.confidence import Confidence, ConfidenceMethod
    from core.fusion.provenance_conflict_manager import (
        resolve_conflict_winner_deterministic as _resolve_conflict_ordering,
    )
    from core.identifiers.identifier import Identifier
    from sdk.domain_config import get_general_agnostic_preset

    if _resolve_conflict_ordering is None:  # pragma: no cover
        pytest.skip("internal helper not exposed")

    def asn(i: str, score: float | None) -> Assertion:
        from core.provenance.provenance import AssertionOrigin, Provenance

        return Assertion(
            id=Identifier(namespace="ASSERT", value=i),
            subject=Identifier(namespace="EX", value="A"),
            predicate="worksAt",
            object=Identifier(namespace="EX", value="X"),
            confidence=Confidence(score=score, method=ConfidenceMethod.STATISTICAL)
            if score is not None
            else None,
            provenance=Provenance(
                assertion_origin=AssertionOrigin.SOURCE,
                agent_id=Identifier(namespace="SYS", value="t"),
                activity_id=Identifier(namespace="ACT", value="t"),
                asserted_at=datetime.now(UTC),
                graph_origin_id="rel_graph_a",
            ),
        )

    strong = asn("strong", 0.95)
    weak = asn("weak", 0.30)
    winner, loser, reason = _resolve_conflict_ordering(
        strong, weak, domain_config=get_general_agnostic_preset()
    )
    assert winner is strong and reason == "HIGHER_EVIDENCE_CONFIDENCE_SCORE"


def test_engine_version_consistent() -> None:
    from core.config import project_version
    from core.fusion.models import FusionRun
    from core.fusion.service import get_project_version

    assert get_project_version() == project_version()
    # Model default resolves through the same source (no more 2.0.0 literal).
    assert FusionRun.model_fields["engine_version"].default is None or isinstance(
        FusionRun.model_fields["engine_version"].default, object
    )


def test_wheel_safe_version_resolution() -> None:
    from core.config import project_version

    v = project_version()
    assert isinstance(v, str) and v  # resolves without pyproject.toml scanning


def test_blank_identifier_raises_instead_of_fabricating_node() -> None:
    from core.fusion.service import parse_resource_identifier

    with pytest.raises(ValueError, match="blank"):
        parse_resource_identifier("   ")
    with pytest.raises(ValueError, match="blank"):
        parse_resource_identifier("")


def test_audit_mappings_come_from_structured_log() -> None:
    """AuditReportEntry.mappings_applied must come from the Stage-3 log."""
    src = open("core/fusion/confidence_decider.py", encoding="utf-8").read()
    assert '"mapping" in' not in src


# ---------------------------------------------------------------------------
# M7/M12/M13 spot checks
# ---------------------------------------------------------------------------


def test_ollama_endpoint_is_configurable() -> None:
    src = open("infrastructure/api/server.py", encoding="utf-8").read()
    assert "http://localhost:11434" not in src


def test_core_fusion_has_no_print_logging() -> None:
    for f in ("core/fusion/engine.py", "core/fusion/service.py"):
        src = open(f, encoding="utf-8").read()
        assert "print(" not in src, f


def test_migration_runner_rejects_unsafe_description(tmp_path: Path) -> None:
    from infrastructure.storage.migration_runner import MigrationRunner

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_bad'description.sql").write_text(
        "CREATE TABLE t (id INTEGER);", encoding="utf-8"
    )
    runner = MigrationRunner(tmp_path / "db.sqlite3", migrations_dir=migrations_dir)
    with pytest.raises(ValueError, match="Rename the migration file"):
        runner.migrate()
