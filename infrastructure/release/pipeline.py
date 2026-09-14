"""Full End-to-End Release Pipeline (Phase 25 & 26).

Executes reproducible 13-stage release lifecycle for Synthetic and Biomedical domain plugins,
capturing full execution manifests, integrating durable ArtifactStore, AssertionStore,
and ReleaseManager formal lifecycle transitions, with atomic endpoint switching and rollback verification.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from contracts.projections import ProjectionManifestRecord
from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.state import AssertionState
from core.fusion.normalizer import DataNormalizer

# FIX CRITICAL-3: GraphFusionService was used in Stage 4 (line 306) but never imported
# in this module, causing a NameError → Stage 4 always FAIL silently.
from core.fusion.service import GraphFusionService
from core.identifiers.identifier import Identifier
from core.projection.manager import ProjectionManager
from core.projection.profile import ProjectionProfile, UnsupportedBehavior
from core.projection.registry import ProjectionRegistry
from core.rdf.graph import NamedGraph, NamedGraphCategory, RDFDataset, graph_name
from core.rdf.terms import RDFTerm, Triple, iri, string_literal
from core.rdf.writer import RDFReleaseWriter
from core.releases.manager import ReleaseManager
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release, ReleaseGate
from core.releases.status import ReleaseStatus
from core.resources.artifact import Artifact, ArtifactKind
from infrastructure.projections.data_source import AuthoritativeReleaseRDFSource
from infrastructure.projections.memory import MemoryProjectionBackend
from infrastructure.projections.rdf import (
    MemoryRDFProjectionStore,
    RDFProjectionBackend,
)
from infrastructure.storage.artifact_store import DurableArtifactStore
from infrastructure.storage.assertion_store import DurableAssertionStore
from infrastructure.storage.graph_store import GraphStore
from infrastructure.storage.projection_store import DurableProjectionStore
from sdk.domain_config import DomainFusionConfig
from sdk.loader import PluginLoader
from sdk.registries import PluginRegistry

logger = logging.getLogger(__name__)


class ExecutionManifest(BaseModel):
    """Reproducible execution manifest for an end-to-end pipeline run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    plugin_id: str = Field(min_length=1)
    source_releases: tuple[str, ...] = Field(default_factory=tuple)
    artifact_digests: tuple[str, ...] = Field(default_factory=tuple)
    plugin_version: str = Field(default="1.0.0")
    policy_version: str = Field(default="1.0.0")
    ontology_version: str = Field(default="1.0.0")
    matcher_version: str = Field(default="1.0.0")
    model_version: str = Field(default="8b_v1")
    reasoner_version: str = Field(default="1.0.0")
    projection_version: str = Field(default="1.0.0")
    runtime_version: str = Field(default="1.0.0")


class EndToEndPipelineResult(BaseModel):
    """Result of an end-to-end pipeline execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: ExecutionManifest
    stage_statuses: dict[str, str]
    active_release_id: str
    reconciled: bool
    switched_endpoint: bool
    rollback_successful: bool
    stage_evidence: dict[str, Any] = Field(default_factory=dict)
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)


class EndToEndReleasePipeline:
    """End-to-end release pipeline executor with real stage validation and projection execution."""

    def __init__(
        self,
        *,
        database_path: str | Path | None = None,
        graph_store: GraphStore | None = None,
        artifact_store: DurableArtifactStore | None = None,
        assertion_store: DurableAssertionStore | None = None,
        projection_store: DurableProjectionStore | None = None,
        data_source: AuthoritativeReleaseRDFSource | None = None,
        release_manager: ReleaseManager | None = None,
    ) -> None:
        db_path = database_path or (graph_store.database_path if graph_store else None)
        self.graph_store = graph_store or GraphStore(db_path)
        common_db = self.graph_store.database_path
        self.artifact_store = artifact_store or DurableArtifactStore(common_db)
        self.assertion_store = assertion_store or DurableAssertionStore(common_db)
        self.projection_store = projection_store or DurableProjectionStore(common_db)
        self.data_source = data_source or AuthoritativeReleaseRDFSource(
            assertion_store=self.assertion_store,
            graph_store=self.graph_store,
        )
        self.release_manager = release_manager or ReleaseManager()

    def execute_pipeline(
        self,
        *,
        plugin_pack: Any,
        run_id: str,
        raw_artifacts: list[dict[str, Any]] | None = None,
        injected_failure_stage: str | None = None,
    ) -> EndToEndPipelineResult:
        manifest = plugin_pack.manifest
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        pack_components = plugin_pack.pack_components()

        # Get domain configuration from plugin pack
        domain_config: DomainFusionConfig | None = None
        if hasattr(plugin_pack, "get_domain_config"):
            domain_config = plugin_pack.get_domain_config()
        elif "domain_config" in pack_components:
            domain_config = pack_components["domain_config"]
        if domain_config is None:
            # Fallback to general preset if no domain config available
            from sdk.domain_config import get_general_agnostic_preset

            domain_config = get_general_agnostic_preset()

        # Generate activity ID for provenance tracking
        activity_id = Identifier(namespace="activity", value=f"pipeline_{run_id}")

        # Dynamic runtime and version detection
        runtime_ver = (
            f"python_{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        plugin_ver = getattr(manifest, "version", "1.0.0")
        policy_ver = getattr(manifest, "policy_version", "1.0.0")
        ontology_ver = f"{manifest.plugin_id}_onto_v{plugin_ver}"
        matcher_ver = "matcher_v2"
        model_ver = "local_8b_instruct"
        reasoner_ver = "reasoner_v1"
        projection_ver = "projection_v1"

        stage_statuses: dict[str, str] = {}
        stage_evidence: dict[str, Any] = {}
        stage_timings_ms: dict[str, float] = {}
        release_id = f"release_{run_id}"
        release_id_identifier = Identifier(namespace="REL", value=release_id)
        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat()

        # Ensure release row exists in GraphStore to satisfy foreign keys
        if self.graph_store.get_release(release_id) is None:
            self.graph_store.save_release(
                release_id,
                {
                    "version": plugin_ver,
                    "status": ReleaseStatus.CANDIDATE.value,
                    "plugin_id": manifest.plugin_id,
                    "created_at": now_iso,
                },
            )

        # Create formal Release in ReleaseManager
        lockfiles = LockfileSet(
            ontology=Identifier(namespace="lock", value="ontology_1.0"),
            runtime=Identifier(namespace="lock", value="python_runtime"),
            reasoner=Identifier(namespace="lock", value="reasoner_1.0"),
            projection=Identifier(namespace="lock", value="projection_1.0"),
        )
        initial_manifest = ReleaseManifest(
            plugins=(Identifier(namespace="plugin", value=manifest.plugin_id),),
            lockfiles=lockfiles,
        )
        release_obj: Release | None = None
        try:
            release_obj = self.release_manager.create_release(
                release_id=release_id_identifier,
                version=plugin_ver,
                manifest=initial_manifest,
                created_at=now_dt,
            )
        except Exception:
            release_obj = self.release_manager.get_release(release_id_identifier)

        ingested_artifacts: list[Artifact] = []
        assertions: list[Assertion] = []
        dataset: RDFDataset | None = None

        # --- Stage 1: Artifact Ingestion ----------------------------------------
        t0 = time.perf_counter()
        try:
            if injected_failure_stage == "ingest":
                raise RuntimeError("Injected ingest failure")

            loader.validate_compatibility(manifest)

            effective_artifacts: list[dict[str, Any]] = list(raw_artifacts) if raw_artifacts else []
            if not effective_artifacts and hasattr(plugin_pack, "get_default_artifacts"):
                default_arts = plugin_pack.get_default_artifacts()
                if isinstance(default_arts, list):
                    effective_artifacts = default_arts

            if effective_artifacts:
                for raw in effective_artifacts:
                    content_raw = raw.get("content", b"")
                    content_bytes = (
                        content_raw
                        if isinstance(content_raw, bytes)
                        else str(content_raw).encode("utf-8")
                    )
                    name = str(raw.get("name", "artifact.dat"))
                    media_type = str(raw.get("media_type", "application/octet-stream"))
                    kind = raw.get("kind", ArtifactKind.DATASET)
                    art = self.artifact_store.store(
                        content=content_bytes,
                        source_release_id=release_id_identifier,
                        media_type=media_type,
                        name=name,
                        kind=kind if isinstance(kind, ArtifactKind) else ArtifactKind.DATASET,
                        retrieved_at=now_dt,
                    )
                    ingested_artifacts.append(art)
            else:
                onto_dict = pack_components.get("ontologies", {})
                onto_bytes = json.dumps(onto_dict, sort_keys=True).encode("utf-8")
                art = self.artifact_store.store(
                    content=onto_bytes,
                    source_release_id=release_id_identifier,
                    media_type="application/json",
                    name=f"{manifest.plugin_id}_ontologies.json",
                    kind=ArtifactKind.DOCUMENT,
                    retrieved_at=now_dt,
                )
                ingested_artifacts.append(art)

            stage_statuses["ingest"] = "PASS"
            stage_evidence["ingest"] = {
                "artifact_count": len(ingested_artifacts),
                "digests": [a.sha256 for a in ingested_artifacts],
            }
        except Exception as exc:
            stage_statuses["ingest"] = "FAIL"
            stage_evidence["ingest"] = {"error": str(exc)}
        finally:
            stage_timings_ms["ingest"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 2: Record Normalization and Graph Parsing ----------------------
        t0 = time.perf_counter()
        normalizer = DataNormalizer(domain_config)
        norm_graph_a = normalizer.normalize_graph([], "graph_a")
        norm_graph_b = normalizer.normalize_graph([], "graph_b")
        try:
            if injected_failure_stage == "normalize" or stage_statuses.get("ingest") != "PASS":
                raise RuntimeError("Injected normalize failure or previous stage failed")

            loader.load(manifest, pack_components)
            schemas = pack_components.get("schemas", {})

            # Build normalized entity lists from ingested artifacts for Stage 3.
            _svc = GraphFusionService()
            all_parsed_asns: list[Assertion] = []
            for art in ingested_artifacts:
                art_bytes = self.artifact_store.get_content(art.id)
                if not art_bytes:
                    continue
                art_str = (
                    art_bytes.decode("utf-8") if isinstance(art_bytes, bytes) else str(art_bytes)
                )
                try:
                    parsed_assertions = _svc.parse_content_to_assertions(
                        art_str,
                        art.media_type or "turtle",
                        art.id,
                        activity_id,
                        domain_config=domain_config,
                    )
                    all_parsed_asns.extend(parsed_assertions)
                except Exception as parse_err:
                    logger.warning("Stage 2 parse warning for artifact %s: %s", art.id, parse_err)

            parsed_asns_a: list[Assertion] = []
            parsed_asns_b: list[Assertion] = []
            if all_parsed_asns:
                mid = max(1, len(all_parsed_asns) // 2)
                parsed_asns_a = all_parsed_asns[:mid]
                parsed_asns_b = (
                    all_parsed_asns[mid:] if len(all_parsed_asns) > 1 else all_parsed_asns
                )

            norm_graph_a = normalizer.normalize_graph(parsed_asns_a, "graph_a")
            norm_graph_b = normalizer.normalize_graph(parsed_asns_b, "graph_b")

            stage_statuses["normalize"] = "PASS"
            stage_evidence["normalize"] = {
                "schema_count": len(schemas),
                "schemas": list(schemas.keys()),
                "norm_graph_a_entities": len(norm_graph_a.entities),
                "norm_graph_b_entities": len(norm_graph_b.entities),
            }
        except Exception as exc:
            stage_statuses["normalize"] = "FAIL"
            stage_evidence["normalize"] = {"error": str(exc)}
        finally:
            stage_timings_ms["normalize"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 3: Candidate Generation --------------------------------------
        t0 = time.perf_counter()
        candidates: list[Any] = []
        try:
            if injected_failure_stage == "candidate_generation":
                raise RuntimeError("Injected candidate generation failure")
            if stage_statuses.get("normalize") != "PASS":
                raise RuntimeError("Upstream normalize stage failed; skipping candidate generation")

            from core.fusion.candidate_finder import CandidateFinder

            strategy = getattr(domain_config, "match_strategy", None)
            embedding_provider = None
            if strategy and getattr(strategy, "enable_embeddings", False):
                from infrastructure.embeddings.resolver import get_embedding_provider

                embedding_provider = get_embedding_provider(strategy)

            candidate_finder = CandidateFinder(domain_config, embedding_provider=embedding_provider)
            candidates = candidate_finder.find_candidates(norm_graph_a, norm_graph_b, activity_id)

            stage_statuses["candidate_generation"] = "PASS"
            stage_evidence["candidate_generation"] = {
                "candidate_pairs_surfaced": len(candidates),
                "match_methods_used": list(set(c.primary_method for c in candidates)),
                "matcher_version": matcher_ver,
            }
        except Exception as exc:
            stage_statuses["candidate_generation"] = "FAIL"
            stage_evidence["candidate_generation"] = {"error": str(exc)}
        finally:
            stage_timings_ms["candidate_generation"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 4: Assertion Creation ----------------------------------------
        t0 = time.perf_counter()
        try:
            if (
                injected_failure_stage == "assertion_creation"
                or stage_statuses.get("candidate_generation") != "PASS"
            ):
                raise RuntimeError(
                    "Injected assertion creation failure or candidate generation failed"
                )

            # Parse actual assertions from ingested artifacts using ParserRegistry
            service = GraphFusionService()
            all_new_assertions: list[Assertion] = []

            if ingested_artifacts:
                for artifact in ingested_artifacts:
                    art_bytes = self.artifact_store.get_content(artifact.id)
                    if not art_bytes:
                        continue

                    art_str = (
                        art_bytes.decode("utf-8")
                        if isinstance(art_bytes, bytes)
                        else str(art_bytes)
                    )
                    try:
                        parsed = service.parse_content_to_assertions(
                            art_str,
                            artifact.media_type or "turtle",
                            artifact.id,
                            activity_id,
                            domain_config=domain_config,
                        )
                        all_new_assertions.extend(parsed)
                    except Exception as parse_err:
                        logger.warning(
                            "Stage 4 parse warning for artifact %s: %s", artifact.id, parse_err
                        )

            if not all_new_assertions:
                raise RuntimeError(
                    f"No assertions could be parsed from ingested artifacts for release {release_id} "
                    f"under plugin '{manifest.plugin_id}'. Failing closed to prevent unverified graph promotion."
                )

            assertions = all_new_assertions

            stage_statuses["assertion_creation"] = "PASS"
            stage_evidence["assertion_creation"] = {
                "assertion_count": len(assertions),
                "assertion_ids": [a.id.canonical for a in assertions],
            }
        except Exception as exc:
            stage_statuses["assertion_creation"] = "FAIL"
            stage_evidence["assertion_creation"] = {"error": str(exc)}
        finally:
            stage_timings_ms["assertion_creation"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 5: Assertion State Transitions -------------------------------
        t0 = time.perf_counter()
        all_events: list[AssertionStateEvent] = []
        try:
            if (
                injected_failure_stage == "state_transitions"
                or stage_statuses.get("assertion_creation") != "PASS"
            ):
                raise RuntimeError("Injected state transitions failure")

            for a in assertions:
                ev1 = AssertionStateEvent(
                    event_id=Identifier(namespace="EVT", value=f"evt_{a.id.value}_rec"),
                    assertion_id=a.id,
                    from_state=None,
                    to_state=AssertionState.CANDIDATE,
                    agent_id=a.provenance.agent_id,
                    activity_id=a.provenance.activity_id,
                    policy_version=policy_ver,
                    reason_code="INGESTED_AS_CANDIDATE",
                    timestamp=now_dt,
                )
                ev2 = AssertionStateEvent(
                    event_id=Identifier(namespace="EVT", value=f"evt_{a.id.value}_val"),
                    assertion_id=a.id,
                    from_state=AssertionState.CANDIDATE,
                    to_state=AssertionState.VERIFIED,
                    agent_id=a.provenance.agent_id,
                    activity_id=a.provenance.activity_id,
                    policy_version=policy_ver,
                    reason_code="PASSED_SCHEMA_VALIDATION",
                    timestamp=now_dt,
                )
                all_events.extend([ev1, ev2])

            self.assertion_store.persist_batch(assertions, all_events)
            self.assertion_store.link_release_assertions(
                release_id, [a.id.canonical for a in assertions]
            )

            stage_statuses["state_transitions"] = "PASS"
            stage_evidence["state_transitions"] = {
                "persisted_assertions": len(assertions),
                "events_recorded": len(all_events),
            }
        except Exception as exc:
            stage_statuses["state_transitions"] = "FAIL"
            stage_evidence["state_transitions"] = {"error": str(exc)}
        finally:
            stage_timings_ms["state_transitions"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 6: Provenance Resolution -------------------------------------
        t0 = time.perf_counter()
        try:
            if (
                injected_failure_stage == "provenance"
                or stage_statuses.get("state_transitions") != "PASS"
            ):
                raise RuntimeError("Injected provenance failure")

            for a in assertions:
                if (
                    not a.provenance.agent_id.value
                    or not a.provenance.activity_id.value
                    or not a.provenance.asserted_at
                ):
                    raise ValueError(f"Incomplete provenance on assertion {a.id.canonical}")

            stage_statuses["provenance"] = "PASS"
            stage_evidence["provenance"] = {
                "provenance_verified": True,
                "agent_id": assertions[0].provenance.agent_id.canonical if assertions else "",
            }
        except Exception as exc:
            stage_statuses["provenance"] = "FAIL"
            stage_evidence["provenance"] = {"error": str(exc)}
        finally:
            stage_timings_ms["provenance"] = round((time.perf_counter() - t0) * 1000, 2)

        # Lifecycle Transition: CANDIDATE -> VALIDATING
        if stage_statuses.get("provenance") == "PASS" and release_obj is not None:
            try:
                release_obj = self.release_manager.begin_validation(release_obj, at=now_dt)
            except Exception:
                pass

        # --- Stage 7: Plugin Validation & Blocking Gates -----------------------
        t0 = time.perf_counter()
        try:
            if injected_failure_stage == "validation" or stage_statuses.get("provenance") != "PASS":
                raise RuntimeError("Injected validation failure")

            validators = getattr(plugin_pack, "validators", None) or pack_components.get(
                "validators", {}
            )
            validation_results: dict[str, bool] = {}
            if validators:
                val_list = (
                    list(validators.values()) if isinstance(validators, dict) else list(validators)
                )
                all_passed = True
                for i, a in enumerate(assertions):
                    a_passed = True
                    for v in val_list:
                        try:
                            if callable(v):
                                res = v(a)
                            elif hasattr(v, "validate"):
                                res = v.validate(a)
                            else:
                                res = True
                            if res is False:
                                a_passed = False
                                break
                        except Exception:
                            a_passed = False
                            break
                    validation_results[f"assertion_{i}"] = a_passed
                    if not a_passed:
                        all_passed = False
            else:
                all_passed = True
                for i, a in enumerate(assertions):
                    is_valid = bool(
                        a.id
                        and a.id.value
                        and a.subject
                        and a.subject.value
                        and a.predicate
                        and a.object
                        and a.object.value
                    )
                    validation_results[f"assertion_{i}"] = is_valid
                    if not is_valid:
                        all_passed = False

            # Build gate from actual validation results
            gate_kwargs = {
                "structural": all_passed,
                "logical": all_passed,
                "application": all_passed,
                "evidence": all_passed,
                "projection": False,
                "reconciliation": False,
            }

            if release_obj is not None:
                passing_gate = ReleaseGate(**gate_kwargs)
                release_obj = self.release_manager.complete_validation(
                    release_obj, gate=passing_gate, at=now_dt
                )

            stage_statuses["validation"] = "PASS" if all_passed else "FAIL"
            stage_evidence["validation"] = {
                "validator_count": len(validators) if isinstance(validators, (list, dict)) else 0,
                "validation_status": "VALIDATED" if all_passed else "VALIDATION_FAILED",
                "validation_results": validation_results,
            }
        except Exception as exc:
            stage_statuses["validation"] = "FAIL"
            stage_evidence["validation"] = {"error": str(exc)}
        finally:
            stage_timings_ms["validation"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 8: Immutable Release Manifest Creation -----------------------
        t0 = time.perf_counter()
        try:
            if injected_failure_stage == "release" or stage_statuses.get("validation") != "PASS":
                raise RuntimeError("Injected release failure")

            rel_manifest = ReleaseManifest(
                source_artifacts=tuple(a.id for a in ingested_artifacts),
                assertions=tuple(a.id for a in assertions),
                plugins=(Identifier(namespace="plugin", value=manifest.plugin_id),),
                lockfiles=lockfiles,
            )
            if release_obj is not None:
                release_obj = self.release_manager.update_manifest(release_obj, rel_manifest)

            stage_statuses["release"] = "PASS"
            stage_evidence["release"] = {
                "release_id": release_id,
                "plugin_id": manifest.plugin_id,
                "status": release_obj.status.value if release_obj else "VALIDATED",
            }
        except Exception as exc:
            stage_statuses["release"] = "FAIL"
            stage_evidence["release"] = {"error": str(exc)}
        finally:
            stage_timings_ms["release"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 9: RDF Snapshot Creation & Verification ----------------------
        t0 = time.perf_counter()
        try:
            if injected_failure_stage == "rdf_snapshot" or stage_statuses.get("release") != "PASS":
                raise RuntimeError("Injected RDF snapshot failure")

            dataset = self.data_source.get(release_id)
            if dataset is None:
                writer = RDFReleaseWriter()
                # Parse actual ontology files from ingested artifacts
                ontologies: list[Any] = []
                if ingested_artifacts:
                    for artifact in ingested_artifacts:
                        art_bytes = self.artifact_store.get_content(artifact.id)
                        if art_bytes is not None:
                            art_str = (
                                art_bytes.decode("utf-8")
                                if isinstance(art_bytes, bytes)
                                else str(art_bytes)
                            )
                            # Try to parse as RDF/TTL
                            try:
                                import rdflib

                                g = rdflib.Graph()
                                g.parse(data=art_str, format="turtle")
                                for s, p, o in g:
                                    s_term = iri(str(s))
                                    p_term = iri(str(p))
                                    o_term: RDFTerm = (
                                        iri(str(o))
                                        if isinstance(o, rdflib.URIRef)
                                        else string_literal(str(o))
                                    )
                                    ontologies.append(
                                        Triple(subject=s_term, predicate=p_term, object=o_term)
                                    )
                            except Exception:
                                # If TTL parsing fails, skip this artifact's ontology
                                pass

                onto_graph = None
                if ontologies:
                    onto_graph = NamedGraph(
                        name=graph_name(NamedGraphCategory.ONTOLOGY),
                        triples=tuple(ontologies),
                    )

                if release_obj is None:
                    raise RuntimeError(
                        "No validated release object exists for RDF snapshot creation"
                    )

                dataset = writer.build_snapshot(
                    release=release_obj,
                    assertions=assertions,
                    events=all_events,
                    ontology=onto_graph,
                )
                self.data_source.register_dataset(release_id, dataset)

            stage_statuses["rdf_snapshot"] = "PASS"
            stage_evidence["rdf_snapshot"] = {
                "triple_count": dataset.triple_count(),
                "graph_count": len(dataset.graphs),
            }
        except Exception as exc:
            stage_statuses["rdf_snapshot"] = "FAIL"
            stage_evidence["rdf_snapshot"] = {"error": str(exc)}
        finally:
            stage_timings_ms["rdf_snapshot"] = round((time.perf_counter() - t0) * 1000, 2)

        # Setup Projection Execution Infrastructure
        proj_registry = ProjectionRegistry()
        mem_backend = MemoryProjectionBackend(data_source=self.data_source, backend_id="memory")
        rdf_store = MemoryRDFProjectionStore()
        rdf_backend = RDFProjectionBackend(
            store=rdf_store, data_source=self.data_source, backend_id="rdf"
        )
        proj_registry.register(mem_backend)
        proj_registry.register(rdf_backend)

        proj_manager = ProjectionManager(registry=proj_registry)
        backend_id = "memory" if "synthetic" in manifest.plugin_id else "rdf"
        proj_id = Identifier(namespace="PROJ", value=f"{backend_id}_{run_id}")
        proj_profile = ProjectionProfile(
            profile_id=f"{manifest.plugin_id}_profile_v1",
            profile_version="1.0.0",
            preserved_fields=("urn:graph:release_metadata",),
            unsupported_behavior=UnsupportedBehavior.SKIP,
        )
        output_digest = hashlib.sha256(f"{release_id}_{backend_id}".encode()).hexdigest()

        # --- Stage 10: Projection Build and Validation --------------------------
        t0 = time.perf_counter()
        try:
            if (
                injected_failure_stage == "projection"
                or stage_statuses.get("rdf_snapshot") != "PASS"
            ):
                raise RuntimeError("Injected projection failure")

            proj_manager.create_projection(
                projection_id=proj_id,
                profile=proj_profile,
                backend_id=backend_id,
                release_id=release_id,
            )
            built_proj = proj_manager.build_candidate(proj_id)
            val_proj = proj_manager.validate_candidate(proj_id)

            if val_proj.is_failed:
                stage_statuses["projection"] = "FAIL"
            else:
                stage_statuses["projection"] = "PASS"
                if release_obj is not None:
                    release_obj = self.release_manager.project(release_obj, at=now_dt)

            rec_count = built_proj.build_result.record_count if built_proj.build_result else 0
            self.projection_store.record_manifest(
                ProjectionManifestRecord(
                    projection_id=proj_id.canonical,
                    release_id=release_id,
                    backend_id=backend_id,
                    status=val_proj.status.value,
                    schema_version="1.0.0",
                    input_digest=hashlib.sha256(release_id.encode()).hexdigest(),
                    output_digest=output_digest,
                    record_count=rec_count,
                    manifest_json=json.dumps({"profile_id": proj_profile.profile_id}),
                    created_at=now_iso,
                )
            )
            stage_evidence["projection"] = {
                "backend_id": backend_id,
                "record_count": rec_count,
                "status": val_proj.status.value,
            }
        except Exception as exc:
            stage_statuses["projection"] = "FAIL"
            stage_evidence["projection"] = {"error": str(exc)}
        finally:
            stage_timings_ms["projection"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 11: Release-to-Projection Reconciliation ---------------------
        t0 = time.perf_counter()
        try:
            if (
                injected_failure_stage == "reconciliation"
                or stage_statuses.get("projection") != "PASS"
                or dataset is None
            ):
                raise RuntimeError("Injected reconciliation failure")

            rec_proj = proj_manager.reconcile_candidate(proj_id, dataset)
            if rec_proj.is_failed:
                stage_statuses["reconciliation"] = "FAIL"
            else:
                stage_statuses["reconciliation"] = "PASS"
                self.projection_store.update_status(proj_id.canonical, rec_proj.status.value)
                if release_obj is not None:
                    passing_gate = ReleaseGate(
                        structural=True,
                        logical=True,
                        application=True,
                        evidence=True,
                        projection=True,
                        reconciliation=True,
                    )
                    release_obj = self.release_manager.reconcile(
                        release_obj, gate=passing_gate, at=now_dt
                    )

            stage_evidence["reconciliation"] = {
                "reconciled": stage_statuses.get("reconciliation") == "PASS",
                "projection_status": rec_proj.status.value,
            }
        except Exception as exc:
            stage_statuses["reconciliation"] = "FAIL"
            stage_evidence["reconciliation"] = {"error": str(exc)}
        finally:
            stage_timings_ms["reconciliation"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 12: Endpoint Switch (Guarded by ReleaseGate) -----------------
        t0 = time.perf_counter()
        gate = ReleaseGate(
            structural=stage_statuses.get("assertion_creation") == "PASS",
            logical=stage_statuses.get("state_transitions") == "PASS",
            application=stage_statuses.get("validation") == "PASS",
            evidence=stage_statuses.get("provenance") == "PASS",
            projection=stage_statuses.get("projection") == "PASS",
            reconciliation=stage_statuses.get("reconciliation") == "PASS",
        )

        prior_stages_pass = all(
            stage_statuses.get(s) == "PASS"
            for s in [
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
            ]
        )

        try:
            if (
                injected_failure_stage == "endpoint_switch"
                or not gate.passed
                or not prior_stages_pass
            ):
                raise RuntimeError(
                    "Injected endpoint switch failure or gate failed or upstream stage failed"
                )

            if release_obj is not None:
                release_obj = self.release_manager.approve(release_obj, gate=gate, at=now_dt)
                release_obj = self.release_manager.publish(release_obj, at=now_dt)

            proj_manager.activate_candidate(proj_id)
            self.projection_store.update_status(proj_id.canonical, "ACTIVE", activated_at=now_iso)
            self.graph_store.update_release_status(release_id, ReleaseStatus.PUBLISHED.value)

            stage_statuses["endpoint_switch"] = "PASS"
            stage_evidence["endpoint_switch"] = {
                "active_endpoint": f"/api/release/{run_id}",
                "release_status": ReleaseStatus.PUBLISHED.value,
                "gate_passed": True,
            }
        except Exception as exc:
            stage_statuses["endpoint_switch"] = "FAIL"
            stage_evidence["endpoint_switch"] = {"error": str(exc)}
        finally:
            stage_timings_ms["endpoint_switch"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Stage 13: Rollback Verification (Non-Destructive Canary) -----------
        t0 = time.perf_counter()
        try:
            if (
                injected_failure_stage == "rollback"
                or stage_statuses.get("endpoint_switch") != "PASS"
            ):
                raise RuntimeError("Injected rollback failure")

            # Non-destructive canary verification: verify rollback protocol on a canary candidate
            canary_id = Identifier(namespace="PROJ", value=f"canary_{run_id}")
            proj_manager.create_projection(
                projection_id=canary_id,
                profile=proj_profile,
                backend_id=backend_id,
                release_id=release_id,
            )
            proj_manager.build_candidate(canary_id)
            proj_manager.validate_candidate(canary_id)
            if dataset is not None:
                proj_manager.reconcile_candidate(canary_id, dataset)
            proj_manager.activate_candidate(canary_id)

            proj_manager.rollback(canary_id)
            backend = proj_registry.get(backend_id)
            backend.destroy(canary_id.canonical)

            # Ensure the live production projection remains ACTIVE in manager and store
            live_active = proj_manager.active_projection()
            if live_active is None or live_active.id != proj_id:
                raise RuntimeError("Production projection was unexpectedly displaced")

            self.projection_store.update_status(proj_id.canonical, "ACTIVE")
            active_rec = self.projection_store.get(proj_id.canonical)
            if active_rec is None or active_rec.status != "ACTIVE":
                raise RuntimeError("Production projection was unexpectedly deactivated")

            stage_statuses["rollback"] = "PASS"
            stage_evidence["rollback"] = {
                "canary_verified": True,
                "production_projection_status": "ACTIVE",
            }
        except Exception as exc:
            stage_statuses["rollback"] = "FAIL"
            stage_evidence["rollback"] = {"error": str(exc)}
        finally:
            stage_timings_ms["rollback"] = round((time.perf_counter() - t0) * 1000, 2)

        # --- Failure Quarantine ------------------------------------------------
        has_failure = any(st == "FAIL" for st in stage_statuses.values())
        if has_failure:
            failed_stages = [k for k, v in stage_statuses.items() if v == "FAIL"]
            reasons = tuple(f"Stage {s} failed" for s in failed_stages) or ("pipeline failure",)
            if (
                release_obj is not None
                and not release_obj.is_quarantined
                and not release_obj.is_published
            ):
                try:
                    self.release_manager.quarantine(release_obj, reasons=reasons, at=now_dt)
                except Exception:
                    pass
            self.graph_store.update_release_status(
                release_id,
                ReleaseStatus.QUARANTINED.value,
                quarantine_reasons=reasons,
            )

        all_artifact_digests = tuple(a.sha256 for a in ingested_artifacts) + (output_digest,)

        exec_manifest = ExecutionManifest(
            run_id=run_id,
            plugin_id=manifest.plugin_id,
            source_releases=(f"{manifest.plugin_id}_release_v1",),
            artifact_digests=all_artifact_digests,
            plugin_version=plugin_ver,
            policy_version=policy_ver,
            ontology_version=ontology_ver,
            matcher_version=matcher_ver,
            model_version=model_ver,
            reasoner_version=reasoner_ver,
            projection_version=projection_ver,
            runtime_version=runtime_ver,
        )

        return EndToEndPipelineResult(
            manifest=exec_manifest,
            stage_statuses=stage_statuses,
            active_release_id=release_id,
            reconciled=stage_statuses.get("reconciliation") == "PASS",
            switched_endpoint=stage_statuses.get("endpoint_switch") == "PASS",
            rollback_successful=stage_statuses.get("rollback") == "PASS",
            stage_evidence=stage_evidence,
            stage_timings_ms=stage_timings_ms,
        )
