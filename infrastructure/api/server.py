"""REST API and Static Web Server for Hybrid Knowledge Graph Platform (Standard Library).

Provides REST endpoints for:
- Ollama local model auto-detection (`GET /api/ollama/models`)
- Graph file upload & parsing (`POST /api/ingest/upload`)
- Domain-agnostic Knowledge Graph Fusion (`POST /api/graph/merge`)
- Visual graph nodes & edges (`GET /api/graph/data`)
- Multi-modal graph query & Ollama LLM QA (`POST /api/graph/query`)
- Entity alignment & Ollama verifier (`POST /api/alignment/verify`)
- 13-stage release pipeline execution (`POST /api/pipeline/execute`)
- System benchmark metrics (`GET /api/benchmarks/metrics`)
- Static file serving for the Web UI frontend.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

from core.artifacts import ArtifactIntegrityError
from core.assertions.assertion import Assertion
from core.entities.entity import Entity, EntityKind
from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.service import GraphFusionService
from core.identifiers.identifier import Identifier
from core.projection.registry import ProjectionRegistry
from core.releases.manager import ReleaseManager
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.resolution.models import CandidateMatch
from infrastructure.benchmarking.benchmark import SystemBenchmarker
from infrastructure.llm.verifier import Local8BVerifier
from infrastructure.projections.data_source import AuthoritativeReleaseRDFSource
from infrastructure.projections.memory import MemoryProjectionBackend
from infrastructure.projections.rdf import (
    MemoryRDFProjectionStore,
    RDFProjectionBackend,
)
from infrastructure.release.pipeline import EndToEndReleasePipeline
from infrastructure.storage import (
    DurableArtifactStore,
    DurableAssertionStore,
    DurableProjectionStore,
    GraphStore,
    backup_database,
    verify_backup,
)

UI_DIR = Path(__file__).resolve().parent.parent.parent / "applications" / "ui"
TESTDATA_DIR = Path(__file__).resolve().parent.parent.parent / "testdata"
MAX_REQUEST_BYTES = int(os.getenv("HYBRID_KG_MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))
CORS_ORIGIN = os.getenv("HYBRID_KG_CORS_ORIGIN", "http://127.0.0.1:8000")

GRAPH_STORE = GraphStore()
ARTIFACT_STORE = DurableArtifactStore(GRAPH_STORE.database_path)
ASSERTION_STORE = DurableAssertionStore(GRAPH_STORE.database_path)
PROJECTION_STORE = DurableProjectionStore(GRAPH_STORE.database_path)

DATA_SOURCE = AuthoritativeReleaseRDFSource(
    assertion_store=ASSERTION_STORE,
    graph_store=GRAPH_STORE,
)
PROJECTION_REGISTRY = ProjectionRegistry()
MEMORY_BACKEND = MemoryProjectionBackend(data_source=DATA_SOURCE, backend_id="memory")
RDF_BACKEND = RDFProjectionBackend(
    store=MemoryRDFProjectionStore(), data_source=DATA_SOURCE, backend_id="rdf"
)
PROJECTION_REGISTRY.register(MEMORY_BACKEND)
PROJECTION_REGISTRY.register(RDF_BACKEND)


def get_domain_pack(pack_name: str) -> Any:
    """Load domain plugin pack via plugin registry / import path.

    Uses the fallback import ``importlib.import_module(f"plugins.{clean_name}")``
    and looks for a class ending in ``DomainPack``.  This avoids hardcoded
    domain-keyword checks in infrastructure code — new plugins are discovered
    by name alone, without requiring server-side edits.
    """
    clean_name = pack_name.lower().replace("-", "_")
    try:
        mod = importlib.import_module(f"plugins.{clean_name}")
        for attr in dir(mod):
            if attr.endswith("DomainPack"):
                return getattr(mod, attr)()
    except ImportError as exc:
        raise ValueError(f"Unknown or uninstalled domain pack '{pack_name}': {exc}") from exc
    raise ValueError(
        f"Domain pack '{pack_name}' could not be initialized — "
        'no ``plugins.{clean_name}" module or DomainPack class found.'
    )


def fetch_ollama_models() -> list[dict[str, str]]:
    """Auto-detect models using `ollama list` CLI and HTTP daemon."""
    models: list[dict[str, str]] = []

    # 1. Try Ollama HTTP API endpoint first
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("models", []):
                    name = item.get("name", "")
                    size_bytes = item.get("size", 0)
                    size_gb = f"{size_bytes / (1024**3):.1f} GB" if size_bytes else "Local"
                    if name:
                        models.append({"name": name, "size": size_gb, "source": "ollama daemon"})
    except Exception:
        pass

    # 2. Try CLI `ollama list` fallback if HTTP endpoint was unreachable
    if not models:
        try:
            proc = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                lines = proc.stdout.strip().splitlines()
                if len(lines) > 1:
                    for line in lines[1:]:
                        parts = line.split()
                        if parts:
                            name = parts[0]
                            size = parts[2] + " " + parts[3] if len(parts) >= 4 else "N/A"
                            models.append({"name": name, "size": size, "source": "ollama cli"})
        except Exception:
            pass

    return models


def query_ollama_model(model_name: str, prompt: str) -> str:
    """Send prompt with active graph context to local Ollama daemon or raise explicit error."""
    active_graph = GRAPH_STORE.get_active()
    active_entities = [n["label"] for n in active_graph["nodes"][:10]]
    context_str = (
        f"Active Knowledge Graph entities: {', '.join(active_entities)}."
        if active_entities
        else "Active Knowledge Graph is empty."
    )
    full_prompt = f"{context_str}\nUser Question: {prompt}"

    try:
        url = "http://localhost:11434/api/generate"
        payload = json.dumps(
            {
                "model": model_name,
                "prompt": full_prompt,
                "stream": False,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                response_text = result.get("response", "").strip()
                if response_text:
                    return cast(str, response_text)
    except Exception as exc:
        raise RuntimeError(f"Ollama query failed: {exc}") from exc

    raise RuntimeError(f"Ollama returned empty response for model '{model_name}'.")


class PlatformRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Hybrid KG API & Web Interface."""

    def log_message(self, format: str, *args: Any) -> None:
        """Silence standard request logging for clean console output."""
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        content = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.end_headers()
        self.wfile.write(content)

    def _send_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/health":
            self._send_json({"status": "ok", "storage": "sqlite", "embeddings": "pluggable"})
            return

        if path == "/api/embeddings/status":
            from infrastructure.embeddings.protocol import (
                EmbeddingProviderUnavailableError,
            )
            from infrastructure.embeddings.resolver import get_embedding_provider

            try:
                provider = get_embedding_provider()
                avail = provider.is_available()
                self._send_json(
                    {
                        "status": "available" if avail else "unavailable",
                        "provider": provider.provider_type,
                        "model_id": provider.model_id,
                        "dimensions": provider.dimensions,
                        "message": "Ready"
                        if avail
                        else f"Provider {provider.provider_type} is not reachable",
                    }
                )
            except EmbeddingProviderUnavailableError as e:
                self._send_json(
                    {
                        "status": "unavailable",
                        "provider": "none",
                        "model_id": "BAAI/bge-large-en-v1.5",
                        "dimensions": 1024,
                        "message": str(e),
                    }
                )
            return

        if path == "/api/ollama/models":
            models = fetch_ollama_models()
            if models:
                self._send_json({"status": "success", "models": models})
            else:
                self._send_json(
                    {
                        "status": "unavailable",
                        "models": [],
                        "message": "Ollama service is not running or no models are installed.",
                    }
                )
            return

        if path == "/api/benchmarks/metrics":
            try:
                benchmarker = SystemBenchmarker()
                res = benchmarker.run_benchmarks()
                self._send_json({"status": "success", "metrics": res.model_dump(mode="json")})
            except Exception as exc:
                self._send_json(
                    {"status": "error", "message": f"Benchmark execution failed: {exc}"},
                    status=500,
                )
            return

        if path == "/api/sample-data":
            samples = [
                {
                    "id": "biomedical_sample_graph",
                    "file_name": "biomedical_sample_graph.ttl",
                    "name": "Biomedical Sample Graph (INS / Metformin / T2D)",
                    "format": "turtle",
                    "domain": "biomedical",
                    "description": "RDF Turtle dataset linking Insulin (HGNC:6018 / P01308), Metformin, and Type 2 Diabetes (MONDO:0005148).",
                },
                {
                    "id": "drug_repurposing_graph",
                    "file_name": "drug_repurposing_graph.csv",
                    "name": "Drug Repurposing Graph (CSV Triples)",
                    "format": "csv",
                    "domain": "biomedical",
                    "description": "Tabular triples with confidence scores and provenance sources for diabetes and cancer targets.",
                },
                {
                    "id": "synthetic_people_org_graph",
                    "file_name": "synthetic_people_org_graph.jsonld",
                    "name": "Synthetic Organization Graph (JSON-LD)",
                    "format": "jsonld",
                    "domain": "synthetic",
                    "description": "JSON-LD graph linking people to companies, departments, and roles.",
                },
            ]
            self._send_json({"status": "success", "samples": samples})
            return

        if path.startswith("/api/sample-data/"):
            sample_id = urllib.parse.unquote(path.removeprefix("/api/sample-data/")).strip()
            sample_file_map = {
                "biomedical": "biomedical_sample_graph.ttl",
                "biomedical_sample_graph": "biomedical_sample_graph.ttl",
                "biomedical_sample_graph.ttl": "biomedical_sample_graph.ttl",
                "drug_repurposing": "drug_repurposing_graph.csv",
                "drug_repurposing_graph": "drug_repurposing_graph.csv",
                "drug_repurposing_graph.csv": "drug_repurposing_graph.csv",
                "synthetic": "synthetic_people_org_graph.jsonld",
                "synthetic_people_org_graph": "synthetic_people_org_graph.jsonld",
                "synthetic_people_org_graph.jsonld": "synthetic_people_org_graph.jsonld",
            }
            file_name = sample_file_map.get(sample_id)
            if not file_name:
                self._send_json(
                    {"status": "error", "message": f"Sample dataset '{sample_id}' not found."},
                    status=404,
                )
                return

            sample_path = TESTDATA_DIR / file_name
            if not sample_path.is_file():
                self._send_json(
                    {
                        "status": "error",
                        "message": f"Sample file '{file_name}' does not exist on disk.",
                    },
                    status=404,
                )
                return

            ext = sample_path.suffix.lower()
            fmt = (
                "turtle" if ext == ".ttl" else ("jsonld" if ext in (".json", ".jsonld") else "csv")
            )
            content = sample_path.read_text(encoding="utf-8")
            self._send_json(
                {
                    "status": "success",
                    "sample_id": sample_id,
                    "file_name": file_name,
                    "format": fmt,
                    "content": content,
                }
            )
            return

        if path == "/api/fusion/configs":
            from sdk.domain_config import DOMAIN_PRESETS

            presets_summary = [
                {
                    "id": p.domain_id,
                    "name": p.domain_name,
                    "description": p.description,
                    "entity_types": [et.name for et in p.entity_types],
                    "config": p.model_dump(mode="json"),
                }
                for p in DOMAIN_PRESETS.values()
            ]
            self._send_json({"status": "success", "presets": presets_summary})
            return

        if path == "/api/graph/data":
            active_graph = GRAPH_STORE.get_active()
            self._send_json(
                {
                    "status": "success",
                    "nodes": active_graph["nodes"],
                    "edges": active_graph["edges"],
                }
            )
            return

        if path == "/api/projections/active":
            try:
                active_records = PROJECTION_STORE.get_all_active()
                self._send_json(
                    {
                        "status": "success",
                        "active_projections": [r.model_dump(mode="json") for r in active_records],
                        "count": len(active_records),
                    }
                )
            except Exception as exc:
                self._send_json(
                    {"status": "error", "message": f"Projection query error: {exc}"}, status=500
                )
            return

        if path.startswith("/api/releases/"):
            release_id = urllib.parse.unquote(path.removeprefix("/api/releases/"))
            release = GRAPH_STORE.get_release(release_id)
            if release is None:
                self._send_json({"status": "error", "message": "Release not found."}, status=404)
            else:
                self._send_json({"status": "success", "release": release})
            return

        if path.startswith("/api/artifacts/"):
            subpath = path.removeprefix("/api/artifacts/")
            if subpath.endswith("/verify"):
                artifact_id_str = urllib.parse.unquote(subpath.removesuffix("/verify"))
                art_id = (
                    Identifier.parse(artifact_id_str)
                    if ":" in artifact_id_str
                    else Identifier(namespace="artifact", value=artifact_id_str)
                )
                try:
                    ARTIFACT_STORE.verify_integrity(art_id)
                    self._send_json(
                        {
                            "status": "ok",
                            "artifact_id": art_id.canonical,
                            "message": "Integrity verified",
                        }
                    )
                except KeyError:
                    self._send_json(
                        {"status": "error", "message": "Artifact not found."}, status=404
                    )
                except ArtifactIntegrityError as exc:
                    self._send_json(
                        {"status": "fail", "error": "digest mismatch", "detail": str(exc)},
                        status=409,
                    )
                return
            else:
                artifact_id_str = urllib.parse.unquote(subpath)
                art_id = (
                    Identifier.parse(artifact_id_str)
                    if ":" in artifact_id_str
                    else Identifier(namespace="artifact", value=artifact_id_str)
                )
                artifact = ARTIFACT_STORE.get(art_id)
                if artifact is None:
                    artifact = ARTIFACT_STORE.by_sha256(artifact_id_str)
                if artifact is None:
                    self._send_json(
                        {"status": "error", "message": "Artifact not found."}, status=404
                    )
                else:
                    self._send_json(
                        {"status": "success", "artifact": artifact.model_dump(mode="json")}
                    )
                return

        if path.startswith("/api/assertions/"):
            assertion_id_str = urllib.parse.unquote(path.removeprefix("/api/assertions/"))
            ass_id = (
                Identifier.parse(assertion_id_str)
                if ":" in assertion_id_str
                else Identifier(namespace="assertion", value=assertion_id_str)
            )
            assertion = ASSERTION_STORE.get_assertion(ass_id)
            if assertion is None:
                self._send_json({"status": "error", "message": "Assertion not found."}, status=404)
            else:
                events = ASSERTION_STORE.get_state_events(assertion.id)
                current_state = (
                    events[-1].to_state.value if events else assertion.status_at_creation.value
                )
                self._send_json(
                    {
                        "status": "success",
                        "assertion": assertion.model_dump(mode="json"),
                        "current_state": current_state,
                        "events": [e.model_dump(mode="json") for e in events],
                    }
                )
            return

        # Serve static web assets
        if path == "/" or path == "/index.html":
            self._send_file(UI_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/styles.css":
            self._send_file(UI_DIR / "styles.css", "text/css")
        elif path == "/app.js":
            self._send_file(UI_DIR / "app.js", "application/javascript")
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Resource not found")

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json({"status": "error", "message": "Invalid Content-Length."}, status=400)
            return
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(
                {
                    "status": "error",
                    "message": f"Request body exceeds the {MAX_REQUEST_BYTES}-byte limit.",
                },
                status=413,
            )
            return
        body = self.rfile.read(content_length)
        data: dict[str, Any] = {}
        if body:
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                self._send_json({"status": "error", "message": "Invalid JSON payload."}, status=400)
                return

        if path == "/api/ingest/upload":
            try:
                content_str = data.get("content", "")
                file_name = data.get("file_name", "dataset.ttl")
                format_type = data.get("format", "turtle")

                service = GraphFusionService()
                activity_id = Identifier(namespace="ACT", value="act_ingest_upload")
                graph_id = Identifier(namespace="graph", value="uploaded_kg")
                assertions = service.parse_content_to_assertions(
                    content_str, format_type, graph_id, activity_id
                )

                # --- Persist raw artifact blob -----------------------------------
                # A sentinel release row is created first so the artifacts FK
                # (source_release_id → releases.release_id) is satisfied.
                ingest_release_id = "upload_transient"
                if GRAPH_STORE.get_release(ingest_release_id) is None:
                    GRAPH_STORE.save_release(
                        ingest_release_id,
                        {"type": "transient_upload", "created_at": datetime.now(UTC).isoformat()},
                    )
                artifact = ARTIFACT_STORE.store(
                    content=content_str.encode("utf-8"),
                    source_release_id=Identifier(namespace="release", value=ingest_release_id),
                    media_type=f"text/{format_type}",
                    name=file_name,
                    retrieved_at=datetime.now(UTC),
                )

                # --- Persist parsed assertions with lineage ----------------------
                if assertions:
                    ASSERTION_STORE.persist_batch(list(assertions), [])

                nodes_map: dict[str, dict[str, Any]] = {}
                edges_list: list[dict[str, Any]] = []

                for a in assertions:
                    s_val = a.subject.value
                    o_val = a.object.value

                    if s_val not in nodes_map:
                        nodes_map[s_val] = {
                            "id": s_val,
                            "label": s_val,
                            "group": "Entity",
                            "color": "#ff6b00",
                        }
                    if o_val not in nodes_map:
                        nodes_map[o_val] = {
                            "id": o_val,
                            "label": o_val,
                            "group": "Entity",
                            "color": "#ffaa00",
                        }

                    edges_list.append({"from": s_val, "to": o_val, "label": a.predicate})

                if nodes_map:
                    GRAPH_STORE.replace_active(list(nodes_map.values()), edges_list)

                records_count = len(assertions)
                self._send_json(
                    {
                        "status": "success",
                        "file_name": file_name,
                        "format": format_type,
                        "parsed_records": records_count,
                        "artifact_id": artifact.id.canonical,
                        "message": f"Successfully parsed {records_count} assertions, persisted artifact and updated active Knowledge Graph store.",
                    }
                )
            except Exception as exc:
                self._send_json(
                    {"status": "error", "message": f"Ingestion error: {exc}"}, status=400
                )
            return

        if path == "/api/graph/merge":
            try:
                graph_a_content = data.get("graph_a_content")
                if not graph_a_content or not str(graph_a_content).strip():
                    self._send_json(
                        {
                            "status": "error",
                            "message": "Missing required field: 'graph_a_content' must not be empty.",
                        },
                        status=400,
                    )
                    return

                graph_b_content = data.get("graph_b_content")
                if not graph_b_content or not str(graph_b_content).strip():
                    self._send_json(
                        {
                            "status": "error",
                            "message": "Missing required field: 'graph_b_content' must not be empty.",
                        },
                        status=400,
                    )
                    return

                graph_a_format = data.get("graph_a_format", "turtle")
                graph_b_format = data.get("graph_b_format", "csv")
                graph_a_id = data.get("graph_a_id", "graph_a")
                graph_b_id = data.get("graph_b_id", "graph_b")
                domain_preset = data.get("domain_preset", "general_agnostic")
                domain_config_data = data.get("domain_config", None)
                graph_a_hash = hashlib.sha256(graph_a_content.encode("utf-8")).hexdigest()
                graph_b_hash = hashlib.sha256(graph_b_content.encode("utf-8")).hexdigest()
                print(
                    f"[API Ingest PHI-Safe Log] Graph A: fmt={graph_a_format}, bytes={len(graph_a_content)}, sha256={graph_a_hash}"
                )
                print(
                    f"[API Ingest PHI-Safe Log] Graph B: fmt={graph_b_format}, bytes={len(graph_b_content)}, sha256={graph_b_hash}"
                )

                conflict_mode_str = data.get("conflict_mode", "conflict_preserve")
                mode = (
                    ConflictMode(conflict_mode_str)
                    if conflict_mode_str in [m.value for m in ConflictMode]
                    else ConflictMode.CONFLICT_PRESERVE
                )

                fusion_req = GraphFusionRequest(
                    graph_a_id=graph_a_id,
                    graph_b_id=graph_b_id,
                    graph_a_content=graph_a_content,
                    graph_a_format=graph_a_format,
                    graph_b_content=graph_b_content,
                    graph_b_format=graph_b_format,
                    conflict_mode=mode,
                    domain_preset=domain_preset,
                    domain_config=domain_config_data,
                )

                service = GraphFusionService()
                fusion_res = service.execute_fusion(fusion_req)
                res_dict = fusion_res.model_dump(mode="json")
                release_id = res_dict["fusion_run"]["result_release_id"]["value"]
                release_identifier = Identifier(namespace="release", value=release_id)

                # --- Persist the release FIRST so artifacts FK is satisfied -----
                # Assertions are persisted next; the release row references them
                # via the release_assertions bridge table.
                raw_assertions = getattr(fusion_res, "assertions", None) or []
                assertion_ids_for_capstone = [a.id.canonical for a in raw_assertions]
                res_dict = GRAPH_STORE.save_release(
                    release_id,
                    res_dict,
                    # Artifact FK validation skipped here — artifacts stored after.
                    assertion_ids=assertion_ids_for_capstone
                    if assertion_ids_for_capstone
                    else None,
                )

                # --- Persist raw artifact blobs (graph A and B source content) ---
                # Release row already exists so the FK constraint is satisfied.
                release_ref = Identifier(namespace="release", value=release_id)
                artifact_a = ARTIFACT_STORE.store(
                    content=graph_a_content.encode("utf-8"),
                    source_release_id=release_ref,
                    media_type=f"text/{graph_a_format}",
                    name=graph_a_id,
                    retrieved_at=datetime.now(UTC),
                )
                artifact_b = ARTIFACT_STORE.store(
                    content=graph_b_content.encode("utf-8"),
                    source_release_id=release_ref,
                    media_type=f"text/{graph_b_format}",
                    name=graph_b_id,
                    retrieved_at=datetime.now(UTC),
                )
                artifact_ids = [artifact_a.id.canonical, artifact_b.id.canonical]

                # --- Persist fused assertions with lineage -----------------------
                if raw_assertions:
                    ASSERTION_STORE.persist_batch(list(raw_assertions), [])

                release_manager = ReleaseManager()
                release_candidate = release_manager.create_release(
                    release_id=release_identifier,
                    version="1.0.0",
                    created_at=datetime.fromisoformat(res_dict["fusion_run"]["created_at"]),
                    manifest=ReleaseManifest(
                        plugins=(Identifier(namespace="domain", value=domain_preset),),
                        lockfiles=LockfileSet(
                            ontology=Identifier(namespace="lock", value="ontology_unknown"),
                            runtime=Identifier(namespace="lock", value="python_runtime"),
                            reasoner=Identifier(namespace="lock", value="reasoner_unknown"),
                            projection=Identifier(namespace="lock", value="projection_pending"),
                        ),
                    ),
                )
                GRAPH_STORE.save_release_lifecycle(
                    release_id, release_candidate.model_dump(mode="json")
                )

                # Update active graph with the newly fused release graph
                if fusion_res.nodes:
                    GRAPH_STORE.replace_active(res_dict["nodes"], res_dict["edges"])

                self._send_json(
                    {
                        "status": "success",
                        "fusion": res_dict,
                        "artifact_ids": artifact_ids,
                        "persisted_assertions": len(raw_assertions),
                    }
                )
            except Exception as exc:
                print(f"[Server Fusion Exception] {exc}")
                self._send_json({"status": "error", "message": f"Fusion error: {exc}"}, status=400)
            return

        if path == "/api/release/rollback":
            try:
                target_release_id = data.get("target_release_id")
                if target_release_id is not None:
                    target_release_id = str(target_release_id).strip() or None

                # 1. Roll back GraphStore active graph snapshots
                previous_graph = GRAPH_STORE.rollback()

                # 2. Roll back Projections across active/registered backends
                active_projections = PROJECTION_STORE.get_all_active()
                demoted_projections: list[str] = []
                restored_projections: list[dict[str, Any]] = []
                active_release_id: str | None = None

                # Find all distinct backends with active projections or in registry
                backend_ids = {p.backend_id for p in active_projections}
                if not backend_ids:
                    backend_ids = set(PROJECTION_STORE.get_known_backends()) or {"memory", "rdf"}

                for b_id in sorted(backend_ids):
                    demoted_rec, restored_rec = PROJECTION_STORE.rollback_projection(
                        b_id, target_release_id=target_release_id
                    )
                    if demoted_rec is not None:
                        demoted_projections.append(demoted_rec.projection_id)
                        # Invoke backend rollback protocol if registered
                        if PROJECTION_REGISTRY.has(b_id):
                            try:
                                backend = PROJECTION_REGISTRY.get(b_id)
                                backend.rollback(demoted_rec.projection_id)
                            except Exception:
                                pass
                    if restored_rec is not None:
                        restored_projections.append(
                            {
                                "projection_id": restored_rec.projection_id,
                                "release_id": restored_rec.release_id,
                                "backend_id": restored_rec.backend_id,
                                "record_count": restored_rec.record_count,
                                "status": restored_rec.status,
                            }
                        )
                        if active_release_id is None:
                            active_release_id = restored_rec.release_id

                # If neither graph snapshots nor projections were restored, return 409 unavailable
                if previous_graph is None and not restored_projections:
                    self._send_json(
                        {
                            "status": "unavailable",
                            "message": "No previous persisted release snapshot or projection is available.",
                        },
                        status=409,
                    )
                    return

                restored_nodes = len(previous_graph["nodes"]) if previous_graph is not None else 0
                restored_edges = len(previous_graph["edges"]) if previous_graph is not None else 0

                self._send_json(
                    {
                        "status": "success",
                        "rollback": {
                            "restored_nodes": restored_nodes,
                            "restored_edges": restored_edges,
                            "durability": "sqlite",
                            "active_release_id": active_release_id,
                            "restored_projections": restored_projections,
                            "demoted_projections": demoted_projections,
                        },
                    }
                )
            except Exception as exc:
                self._send_json(
                    {"status": "error", "message": f"Rollback error: {exc}"}, status=500
                )
            return

        if path == "/api/graph/query":
            try:
                query = data.get("query", "").strip()
                if not query:
                    self._send_json(
                        {"status": "error", "message": "Query string must not be empty."},
                        status=400,
                    )
                    return

                model = data.get("model", "").strip()
                if not model:
                    self._send_json(
                        {
                            "status": "error",
                            "message": "Model parameter is required for graph query.",
                        },
                        status=400,
                    )
                    return

                llm_response = query_ollama_model(model, query)

                self._send_json(
                    {
                        "status": "success",
                        "query": query,
                        "model_used": model,
                        "answer": llm_response,
                    }
                )
            except Exception as exc:
                self._send_json({"status": "error", "message": f"Query error: {exc}"}, status=503)
            return

        if path == "/api/alignment/verify":
            try:
                pair = data.get("pair", {})
                model = data.get("model", "llama3.1:8b-instruct-q8_0")
                score = float(data.get("confidence", 0.88))

                source_label = pair.get("source")
                target_label = pair.get("target")

                active_graph = GRAPH_STORE.get_active()
                all_nodes = active_graph.get("nodes", [])

                # Look up actual entities from the active graph by label or id
                if not source_label and all_nodes:
                    source_label = all_nodes[0].get("label") or all_nodes[0].get("id")
                if not target_label and len(all_nodes) > 1:
                    target_label = all_nodes[1].get("label") or all_nodes[1].get("id")

                if not source_label or not target_label:
                    self._send_json(
                        {
                            "status": "error",
                            "message": "Missing required entity labels in 'pair': both 'source' and 'target' must be provided or identifiable from the graph.",
                        },
                        status=400,
                    )
                    return

                def _find_or_build_entity(val_or_label: Any) -> Entity:
                    val_str = str(val_or_label).strip()
                    v_low = val_str.lower()
                    for n in all_nodes:
                        if (
                            str(n.get("id", "")).lower() == v_low
                            or str(n.get("label", "")).lower() == v_low
                        ):
                            node_id = str(n.get("id") or val_str)
                            node_label = str(n.get("label") or node_id)
                            c_id = n.get("canonical_id")
                            if c_id and ":" in str(c_id):
                                ns, val = str(c_id).split(":", 1)
                                return Entity(
                                    id=Identifier(namespace=ns, value=val),
                                    kind=EntityKind.CONCEPT,
                                    label=node_label,
                                )
                            return Entity(
                                id=Identifier(namespace="ENTITY", value=node_id),
                                kind=EntityKind.CONCEPT,
                                label=node_label,
                            )
                    if ":" in val_str:
                        ns, val = val_str.split(":", 1)
                        return Entity(
                            id=Identifier(namespace=ns, value=val),
                            kind=EntityKind.CONCEPT,
                            label=val_str,
                        )
                    return Entity(
                        id=Identifier(namespace="ENTITY", value=val_str),
                        kind=EntityKind.CONCEPT,
                        label=val_str,
                    )

                source_ent = _find_or_build_entity(source_label)
                target_ent = _find_or_build_entity(target_label)
                candidate = CandidateMatch(
                    source_entity=source_ent,
                    candidate_entity=target_ent,
                    ranking_score=score,
                    ranking_method="vector_similarity",
                    activity_id=Identifier(namespace="ACT", value="act_candidate_gen_1"),
                )

                verifier = Local8BVerifier()
                v_resp, _ = verifier.verify(source_ent, candidate)
                res_dict = v_resp.model_dump(mode="json")
                res_dict["model_used"] = model
                if "MODEL_PROVIDER_UNAVAILABLE" in v_resp.reason_codes:
                    self._send_json(
                        {
                            "status": "unavailable",
                            "verification": res_dict,
                            "message": f"Model provider is unavailable for '{model}'.",
                        },
                        status=503,
                    )
                    return
                self._send_json({"status": "success", "verification": res_dict})
            except Exception as exc:
                self._send_json(
                    {"status": "error", "message": f"Verification error: {exc}"}, status=400
                )
            return

        if path == "/api/pipeline/execute":
            try:
                pipeline_type = data.get("pipeline_type", "e2e_release")
                run_id = data.get("run_id", "run_web_001")

                if pipeline_type == "drug_repurposing":
                    mod = importlib.import_module("applications.drug_repurposing.workflow")
                    DrugRepurposingPipeline = mod.DrugRepurposingPipeline
                    AssertionStoreLayers = mod.AssertionStoreLayers

                    raw_disease = data.get("target_disease", "MONDO:0005148")
                    if ":" in raw_disease:
                        ns, val = raw_disease.split(":", 1)
                        disease_id = Identifier(namespace=ns, value=val)
                    else:
                        disease_id = Identifier(namespace="MONDO", value=raw_disease)

                    pipeline = DrugRepurposingPipeline(
                        agent_id=Identifier(namespace="SYS", value="AGENT_WEB"),
                        activity_id=Identifier(namespace="SYS", value=f"ACT_REPURPOSE_{run_id}"),
                    )

                    # Query real production assertions from ASSERTION_STORE
                    release_id = data.get("release_id")
                    prod_assertions: list[Assertion] = []
                    if release_id:
                        prod_assertions = list(ASSERTION_STORE.get_by_release(release_id))
                    else:
                        active_projections = PROJECTION_STORE.get_all_active()
                        if active_projections:
                            for proj in active_projections:
                                fetched = list(ASSERTION_STORE.get_by_release(proj.release_id))
                                if fetched:
                                    prod_assertions.extend(fetched)
                        if not prod_assertions:
                            # Try to find assertions from the most recent release
                            with GRAPH_STORE._session() as conn:
                                rel_row = conn.execute(
                                    "SELECT release_id FROM releases ORDER BY rowid DESC LIMIT 1"
                                ).fetchone()
                                if rel_row:
                                    prod_assertions = list(
                                        ASSERTION_STORE.get_by_release(rel_row["release_id"])
                                    )
                        if not prod_assertions:
                            # Fallback to all assertions in store
                            with ASSERTION_STORE._session() as conn:
                                rows = conn.execute(
                                    "SELECT * FROM assertions ORDER BY created_at ASC"
                                ).fetchall()
                                prod_assertions = [
                                    ASSERTION_STORE._row_to_assertion(r) for r in rows
                                ]

                    layers = AssertionStoreLayers(production=prod_assertions)
                    hypotheses = pipeline.generate_hypotheses(
                        target_disease_id=disease_id,
                        layers=layers,
                    )
                    self._send_json(
                        {
                            "status": "success",
                            "pipeline_type": "drug_repurposing",
                            "hypotheses_generated": len(hypotheses),
                            "hypotheses": [h.model_dump(mode="json") for h in hypotheses],
                            "target_disease": disease_id.canonical,
                            "layer": "hypothesis",
                        }
                    )
                else:
                    e2e = EndToEndReleasePipeline(
                        graph_store=GRAPH_STORE,
                        artifact_store=ARTIFACT_STORE,
                        assertion_store=ASSERTION_STORE,
                        projection_store=PROJECTION_STORE,
                        data_source=DATA_SOURCE,
                    )
                    pack_name = data.get("domain_pack", "biomedical")
                    pack = get_domain_pack(pack_name)
                    result = e2e.execute_pipeline(plugin_pack=pack, run_id=run_id)
                    self._send_json(
                        {
                            "status": "success",
                            "pipeline_type": "e2e_release",
                            "run_result": result.model_dump(mode="json"),
                        }
                    )
            except Exception as exc:
                self._send_json(
                    {"status": "error", "message": f"Pipeline execution error: {exc}"}, status=400
                )
        if path == "/api/backup":
            try:
                backup_dir_str = data.get("backup_dir", "backups")
                backup_dir = Path(backup_dir_str)
                backup_dir.mkdir(parents=True, exist_ok=True)
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f"hybrid_kg_backup_{timestamp_str}.sqlite3"
                backup_path = backup_dir / backup_filename
                backup_database(GRAPH_STORE.database_path, backup_path)
                is_valid = verify_backup(backup_path)
                if not is_valid:
                    self._send_json(
                        {"status": "error", "message": "Backup integrity verification failed."},
                        status=500,
                    )
                else:
                    self._send_json(
                        {
                            "status": "success",
                            "backup_path": str(backup_path),
                            "verified": True,
                        }
                    )
            except Exception as exc:
                self._send_json({"status": "error", "message": f"Backup failed: {exc}"}, status=500)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")


def create_server(host: str = "127.0.0.1", port: int = 8000) -> tuple[HTTPServer, int]:
    """Create HTTPServer with fallback port binding if target port is occupied."""
    for p in range(port, port + 10):
        try:
            srv = HTTPServer((host, p), PlatformRequestHandler)
            return srv, p
        except OSError:
            continue
    srv = HTTPServer((host, 0), PlatformRequestHandler)
    return srv, srv.server_port


if __name__ == "__main__":
    server, active_port = create_server()
    print(f"Server starting on http://127.0.0.1:{active_port}...")
    server.serve_forever()
