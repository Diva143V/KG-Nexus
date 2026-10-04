"""ApplicationCore: the deep module owning platform state and domain handlers.

Composition root for the platform's durable stores, plugin registries, and
release pipeline. Every HTTP handler lives here as a plain function from a
:class:`~infrastructure.api.router.RequestContext` to a
:class:`~infrastructure.api.router.Response` — no sockets, no headers.

Stores bind lazily via :meth:`ApplicationCore.stores` snapshotting the module
-level ``GRAPH_STORE``/``ARTIFACT_STORE``/``ASSERTION_STORE``/
``PROJECTION_STORE`` variables in ``infrastructure.api.server`` at request
time. Tests swap those globals before booting a server; per-request binding
keeps that contract intact without leaking globals into handler code.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.artifacts import ArtifactIntegrityError
from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.state import AssertionState
from core.entities.entity import Entity, EntityKind
from core.fusion.models import ConflictMode, GraphFusionRequest
from core.fusion.service import GraphFusionService
from core.health import healthcheck
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from core.releases.manager import ReleaseManager
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.resolution.models import CandidateMatch
from infrastructure.api import ollama_client
from infrastructure.api.graph_intelligence import GraphIntelligenceMixin
from infrastructure.api.router import RequestContext, RequestRouter, Response, Route
from infrastructure.benchmarking.benchmark import SystemBenchmarker
from infrastructure.llm.verifier import Local8BVerifier
from infrastructure.projections import create_default_projection_registry
from infrastructure.projections.data_source import AuthoritativeReleaseRDFSource
from infrastructure.release.pipeline import EndToEndReleasePipeline
from infrastructure.storage import (
    DurableArtifactStore,
    DurableAssertionStore,
    DurableProjectionStore,
    GraphStore,
    backup_database,
    verify_backup,
)
from sdk.loader import PluginLoader
from sdk.registries import PluginRegistry as SdkPluginRegistry

logger = logging.getLogger("hybrid_kg.api")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

UI_DIR = ROOT_DIR / "applications" / "ui"
TESTDATA_DIR = ROOT_DIR / "testdata"

_BENCHMARK_CACHE_TTL_SEC = 120.0

_SAMPLE_FILE_MAP: dict[str, str] = {
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

_SAMPLE_CATALOG: list[dict[str, str]] = [
    {
        "id": "biomedical_sample_graph",
        "file_name": "biomedical_sample_graph.ttl",
        "name": "Biomedical Sample Graph (INS / Metformin / T2D)",
        "format": "turtle",
        "domain": "biomedical",
        "description": (
            "RDF Turtle dataset linking Insulin (HGNC:6018 / P01308), Metformin, "
            "and Type 2 Diabetes (MONDO:0005148)."
        ),
    },
    {
        "id": "drug_repurposing_graph",
        "file_name": "drug_repurposing_graph.csv",
        "name": "Drug Repurposing Graph (CSV Triples)",
        "format": "csv",
        "domain": "biomedical",
        "description": (
            "Tabular triples with confidence scores and provenance sources "
            "for diabetes and cancer targets."
        ),
    },
    {
        "id": "synthetic_people_org_graph",
        "file_name": "synthetic_people_org_graph.jsonld",
        "name": "Synthetic Organization Graph (JSON-LD)",
        "format": "jsonld",
        "domain": "synthetic",
        "description": ("JSON-LD graph linking people to companies, departments, and roles."),
    },
]

# Curated alignment pairs guaranteeing rich visual exploration even on an
# empty active graph. Kept as data: the handler only extends its results.
_CURATED_ALIGNMENT_PAIRS: list[dict[str, Any]] = [
    {
        "id": "cand_egfr_gene_prot",
        "source": {
            "id": "HGNC:3236",
            "label": "EGFR Gene",
            "group": "Gene",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "LOCUS:7p11.2",
                    "label": "chr7p11.2 (Genomic Locus)",
                    "rel": "located_on",
                    "group": "Genomic",
                },
                {
                    "id": "UniProt:P00533",
                    "label": "UniProt:P00533 (EGFR)",
                    "rel": "encodes",
                    "group": "Protein",
                },
                {
                    "id": "MONDO:0005267",
                    "label": "Non-Small Cell Lung Carcinoma (MONDO:0005267)",
                    "rel": "associated_with",
                    "group": "Disease",
                },
                {
                    "id": "LIGAND:EGF",
                    "label": "Epidermal Growth Factor (EGF)",
                    "rel": "regulated_by",
                    "group": "Ligand",
                },
            ],
        },
        "target": {
            "id": "UniProt:P00533",
            "label": "EGFR Protein (Epidermal Growth Factor Receptor)",
            "group": "Protein",
            "edges_count": 5,
            "neighbors": [
                {
                    "id": "CHEMBL:3353410",
                    "label": "Osimertinib (CHEMBL:3353410)",
                    "rel": "inhibited_by",
                    "group": "Drug",
                },
                {
                    "id": "IPR000719",
                    "label": "Tyrosine Kinase Domain",
                    "rel": "has_domain",
                    "group": "Domain",
                },
                {
                    "id": "MONDO:0005267",
                    "label": "Non-Small Cell Lung Carcinoma (MONDO:0005267)",
                    "rel": "implicated_in",
                    "group": "Disease",
                },
                {
                    "id": "TF:STAT3",
                    "label": "STAT3 Transcription Factor",
                    "rel": "activates",
                    "group": "Protein",
                },
                {
                    "id": "SITE:T790",
                    "label": "ATP Binding Site (Thr790)",
                    "rel": "has_site",
                    "group": "Site",
                },
            ],
        },
        "similarity": 0.88,
        "status": "BORDERLINE",
        "source_graph": "HGNC (Graph A)",
        "target_graph": "UniProt (Graph B)",
    },
    {
        "id": "cand_osimertinib_azd",
        "source": {
            "id": "CHEMBL:3353410",
            "label": "Osimertinib",
            "group": "Drug",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "UniProt:P00533",
                    "label": "EGFR Protein (UniProt:P00533)",
                    "rel": "targets",
                    "group": "Protein",
                },
                {
                    "id": "MONDO:0005267",
                    "label": "Non-Small Cell Lung Carcinoma (MONDO:0005267)",
                    "rel": "treats",
                    "group": "Disease",
                },
                {
                    "id": "MOA:KinaseInhibitor",
                    "label": "Irreversible Tyrosine Kinase Inhibitor",
                    "rel": "has_mechanism",
                    "group": "Mechanism",
                },
                {
                    "id": "FDA:Approved_2015",
                    "label": "FDA Approved (Tagrisso 2015)",
                    "rel": "regulatory_status",
                    "group": "Regulatory",
                },
            ],
        },
        "target": {
            "id": "PubChem:CID71496458",
            "label": "AZD9291 (Tagrisso)",
            "group": "Compound",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "UniProt:P00533",
                    "label": "EGFR Protein (UniProt:P00533)",
                    "rel": "molecular_target",
                    "group": "Protein",
                },
                {
                    "id": "CHEMBL:3353410",
                    "label": "Osimertinib Free Base (CHEMBL:3353410)",
                    "rel": "cross_reference",
                    "group": "Compound",
                },
                {
                    "id": "FORMULA:C28H33N7O2",
                    "label": "Formula: C28H33N7O2",
                    "rel": "has_formula",
                    "group": "Chemistry",
                },
                {
                    "id": "PROP:MW499.6",
                    "label": "Molecular Weight: 499.6 g/mol",
                    "rel": "has_property",
                    "group": "Chemistry",
                },
            ],
        },
        "similarity": 0.94,
        "status": "BORDERLINE",
        "source_graph": "ChEMBL (Graph A)",
        "target_graph": "PubChem (Graph B)",
    },
    {
        "id": "cand_metformin_glucophage",
        "source": {
            "id": "CHEMBL:1431",
            "label": "Metformin",
            "group": "Drug",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "MONDO:0005148",
                    "label": "Type 2 Diabetes Mellitus (MONDO:0005148)",
                    "rel": "treats",
                    "group": "Disease",
                },
                {
                    "id": "TARGET:PRKAA1",
                    "label": "AMPK Alpha-1 Subunit (PRKAA1)",
                    "rel": "activates",
                    "group": "Protein",
                },
                {
                    "id": "PATHWAY:ComplexI",
                    "label": "Mitochondrial Complex I",
                    "rel": "inhibits",
                    "group": "Complex",
                },
                {
                    "id": "CLASS:Biguanide",
                    "label": "Biguanide Class Derivative",
                    "rel": "subclass_of",
                    "group": "Class",
                },
            ],
        },
        "target": {
            "id": "DrugBank:DB00331",
            "label": "Glucophage (Metformin Hydrochloride)",
            "group": "Pharmaceutical",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "MONDO:0005148",
                    "label": "Type 2 Diabetes Mellitus (MONDO:0005148)",
                    "rel": "indicated_for",
                    "group": "Disease",
                },
                {
                    "id": "DOSAGE:OralER",
                    "label": "Oral Extended-Release Tablet (500mg)",
                    "rel": "dosage_form",
                    "group": "Formulation",
                },
                {
                    "id": "MOIETY:HCl",
                    "label": "Hydrochloride Salt Adduct (HCl)",
                    "rel": "has_salt_moiety",
                    "group": "Chemistry",
                },
                {
                    "id": "TARGET:PRKAA1",
                    "label": "AMPK Alpha-1 Subunit (PRKAA1)",
                    "rel": "target_protein",
                    "group": "Protein",
                },
            ],
        },
        "similarity": 0.86,
        "status": "REVIEW",
        "source_graph": "ChEMBL (Graph A)",
        "target_graph": "DrugBank (Graph B)",
    },
    {
        "id": "cand_braf_gene_prot",
        "source": {
            "id": "HGNC:1097",
            "label": "BRAF Gene",
            "group": "Gene",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "LOCUS:7q34",
                    "label": "chr7q34 (Genomic Locus)",
                    "rel": "located_on",
                    "group": "Genomic",
                },
                {
                    "id": "UniProt:P15056",
                    "label": "UniProt:P15056 (BRAF Kinase)",
                    "rel": "encodes",
                    "group": "Protein",
                },
                {
                    "id": "MONDO:0005105",
                    "label": "Cutaneous Melanoma (MONDO:0005105)",
                    "rel": "associated_with",
                    "group": "Disease",
                },
                {
                    "id": "PATHWAY:MAPK",
                    "label": "MAPK / ERK Signaling Cascade",
                    "rel": "in_pathway",
                    "group": "Pathway",
                },
            ],
        },
        "target": {
            "id": "UniProt:P15056",
            "label": "Serine/threonine-protein kinase B-raf",
            "group": "Protein",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "CHEMBL:1229517",
                    "label": "Vemurafenib (CHEMBL:1229517)",
                    "rel": "inhibited_by",
                    "group": "Drug",
                },
                {
                    "id": "KINASE:MAP2K1",
                    "label": "MEK1 Kinase (MAP2K1)",
                    "rel": "phosphorylates",
                    "group": "Protein",
                },
                {
                    "id": "MUTATION:V600E",
                    "label": "Activating Mutation (V600E)",
                    "rel": "has_variant",
                    "group": "Variant",
                },
                {
                    "id": "MONDO:0005105",
                    "label": "Cutaneous Melanoma (MONDO:0005105)",
                    "rel": "disease_involvement",
                    "group": "Disease",
                },
            ],
        },
        "similarity": 0.79,
        "status": "BORDERLINE",
        "source_graph": "HGNC (Graph A)",
        "target_graph": "UniProt (Graph B)",
    },
    {
        "id": "cand_ins_gene_prot",
        "source": {
            "id": "HGNC:6018",
            "label": "INS Gene",
            "group": "Gene",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "LOCUS:11p15.5",
                    "label": "chr11p15.5 (Genomic Locus)",
                    "rel": "located_on",
                    "group": "Genomic",
                },
                {
                    "id": "CELL:BetaCell",
                    "label": "Pancreatic Beta Cells",
                    "rel": "expressed_in",
                    "group": "Tissue",
                },
                {
                    "id": "MONDO:0005147",
                    "label": "Type 1 Diabetes Mellitus (MONDO:0005147)",
                    "rel": "associated_with",
                    "group": "Disease",
                },
                {
                    "id": "UniProt:P01308",
                    "label": "Insulin Precursor (P01308)",
                    "rel": "encodes",
                    "group": "Protein",
                },
            ],
        },
        "target": {
            "id": "UniProt:P01308",
            "label": "Insulin Precursor",
            "group": "Protein",
            "edges_count": 4,
            "neighbors": [
                {
                    "id": "RECEPTOR:INSR",
                    "label": "Insulin Receptor (INSR)",
                    "rel": "binds_to",
                    "group": "Receptor",
                },
                {
                    "id": "PHYSIO:Glucose",
                    "label": "Blood Glucose Homeostasis",
                    "rel": "regulates",
                    "group": "Process",
                },
                {
                    "id": "TRANSPORTER:GLUT4",
                    "label": "GLUT4 Transporter (SLC2A4)",
                    "rel": "stimulates_translocation",
                    "group": "Protein",
                },
                {
                    "id": "MONDO:0005147",
                    "label": "Type 1 Diabetes Mellitus (MONDO:0005147)",
                    "rel": "deficiency_causes",
                    "group": "Disease",
                },
            ],
        },
        "similarity": 0.82,
        "status": "REVIEW",
        "source_graph": "HGNC (Graph A)",
        "target_graph": "UniProt (Graph B)",
    },
]


class ApplicationCore(GraphIntelligenceMixin):
    """Owns platform state; every handler is a pure ctx→Response function."""

    def __init__(
        self,
        *,
        graph_store: GraphStore,
        artifact_store: DurableArtifactStore,
        assertion_store: DurableAssertionStore,
        projection_store: DurableProjectionStore,
    ) -> None:
        self.graph_store = graph_store
        self.artifact_store = artifact_store
        self.assertion_store = assertion_store
        self.projection_store = projection_store
        # Track which stores were injected vs defaulted: injected stores win
        # over the module globals (tests construct cores directly); defaulted
        # stores defer to the globals at request time so tests that reassign
        # infrastructure.api.server.* keep working.
        self._stores_injected = {
            "graph": graph_store is not None,
            "artifact": artifact_store is not None,
            "assertion": assertion_store is not None,
            "projection": projection_store is not None,
        }

        self.data_source = AuthoritativeReleaseRDFSource(
            assertion_store=assertion_store,
            graph_store=graph_store,
        )
        self.projection_registry = create_default_projection_registry(
            self.data_source, include_all=True
        )
        self.memory_backend = self.projection_registry.get("memory")
        self.rdf_backend = self.projection_registry.get("rdf")

        self.plugin_registry = SdkPluginRegistry()
        self.plugin_loader = PluginLoader(registry=self.plugin_registry)

        # Composition root: bundled plugin packs register their domain presets
        # so API endpoints and resolve_domain_config callers see the catalogue.
        for bundled_pack in ("biomedical", "synthetic"):
            try:
                importlib.import_module(f"plugins.{bundled_pack}")
            except ImportError:
                pass

        try:
            from applications.drug_repurposing import run_drug_repurposing_pipeline

            self.plugin_registry.workflows.register(
                "drug_repurposing", run_drug_repurposing_pipeline
            )
        except ImportError:
            pass

        self._benchmark_lock = threading.Lock()
        self._benchmark_cache: dict[str, Any] | None = None
        self._benchmark_cache_time: float = 0.0
        self._router: RequestRouter | None = None

    # ------------------------------------------------------------------
    # Store accessors — module globals read at request time so tests that
    # reassign infrastructure.api.server.{GRAPH_STORE,...} keep working.
    # ------------------------------------------------------------------

    @property
    def stores(self) -> dict[str, Any]:
        from infrastructure.api import server as server_module

        return {
            "graph": server_module.GRAPH_STORE,
            "artifact": server_module.ARTIFACT_STORE,
            "assertion": server_module.ASSERTION_STORE,
            "projection": server_module.PROJECTION_STORE,
        }

    @property
    def graph(self) -> GraphStore:
        if self._stores_injected["graph"]:
            return self.graph_store
        from infrastructure.api import server as server_module

        return server_module.GRAPH_STORE

    @property
    def artifacts(self) -> DurableArtifactStore:
        if self._stores_injected["artifact"]:
            return self.artifact_store
        from infrastructure.api import server as server_module

        return server_module.ARTIFACT_STORE

    @property
    def assertions(self) -> DurableAssertionStore:
        if self._stores_injected["assertion"]:
            return self.assertion_store
        from infrastructure.api import server as server_module

        return server_module.ASSERTION_STORE

    @property
    def projections(self) -> DurableProjectionStore:
        if self._stores_injected["projection"]:
            return self.projection_store
        from infrastructure.api import server as server_module

        return server_module.PROJECTION_STORE

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def safe_identifier(val: str, default_ns: str = "ENTITY") -> Identifier:
        """Construct a whitespace-safe Identifier from any arbitrary string."""
        raw = str(val).strip()
        if not raw:
            return Identifier(namespace=default_ns, value="unknown")
        if ":" in raw:
            ns, v = raw.split(":", 1)
            safe_ns = re.sub(r"[^\w\-.]", "_", ns.strip()) or default_ns
            safe_v = re.sub(r"[^\w\-.]", "_", v.strip()) or "val"
            return Identifier(namespace=safe_ns, value=safe_v)
        safe_v = re.sub(r"[^\w\-.]", "_", raw)
        return Identifier(namespace=default_ns, value=safe_v)

    def get_domain_pack(self, pack_name: str) -> Any:
        """Load domain plugin pack via formal PluginLoader and PluginRegistry."""
        return self.plugin_loader.discover_and_load_pack(pack_name)

    def router(self) -> RequestRouter:
        """The route table, built once per core."""
        if self._router is None:
            self._router = self.build_router()
        return self._router

    # ------------------------------------------------------------------
    # Router assembly — the route table IS the interface documentation.
    # ------------------------------------------------------------------

    def build_router(self) -> RequestRouter:
        return RequestRouter(
            [
                # -- GET ---------------------------------------------------
                Route("GET", "/health", self.get_health),
                Route("GET", "/api/embeddings/status", self.get_embeddings_status),
                Route("GET", "/api/ollama/models", self.get_ollama_models),
                Route("GET", "/api/benchmarks/metrics", self.get_benchmarks),
                Route("GET", "/api/sample-data", self.get_sample_data_list),
                Route("GET", "/api/sample-data/<rest...>", self.get_sample_data_file),
                Route("GET", "/api/fusion/configs", self.get_fusion_configs),
                Route("GET", "/api/graph/data", self.get_graph_data),
                Route("GET", "/api/entities/by-type", self.get_entities_by_type),
                Route("GET", "/api/diseases/detected", self.get_diseases_detected),
                Route("GET", "/api/projections/active", self.get_active_projections),
                Route("GET", "/api/releases/<release_id>", self.get_release),
                Route("GET", "/api/artifacts/<rest...>", self.get_artifact),
                Route("GET", "/api/assertions/<assertion_id>", self.get_assertion),
                Route("GET", "/api/entities/<rest...>", self.get_entity_assertions),
                Route("GET", "/api/releases", self.get_release_list),
                Route("GET", "/api/graph/diff", self.get_graph_diff),
                Route("POST", "/api/graph/search", self.post_graph_search),
                Route("POST", "/api/graph/paths", self.post_graph_paths),
                Route("GET", "/api/alignment/candidates", self.get_alignment_candidates),
                Route("GET", "/", self.get_index),
                Route("GET", "/index.html", self.get_index),
                Route("GET", "/alignment_studio", self.get_alignment_studio),
                Route("GET", "/alignment_studio.html", self.get_alignment_studio),
                Route("GET", "/alignment-studio", self.get_alignment_studio),
                Route("GET", "/alignment-studio.html", self.get_alignment_studio),
                Route("GET", "/alignment_studio.css", self.get_alignment_studio_css),
                Route("GET", "/alignment-studio.css", self.get_alignment_studio_css),
                Route("GET", "/alignment_studio.js", self.get_alignment_studio_js),
                Route("GET", "/alignment-studio.js", self.get_alignment_studio_js),
                Route("GET", "/auth_client.js", self.get_auth_client_js),
                Route("GET", "/theme.js", self.get_theme_js),
                Route("GET", "/canvas_layout.js", self.get_canvas_layout_js),
                Route("GET", "/boot.js", self.get_boot_js),
                Route("GET", "/graph_preview.js", self.get_graph_preview_js),
                Route("GET", "/lineage.js", self.get_lineage_js),
                Route("GET", "/timetravel.js", self.get_timetravel_js),
                Route("GET", "/sandbox.js", self.get_sandbox_js),
                Route("GET", "/styles.css", self.get_styles),
                Route("GET", "/app.js", self.get_app_js),
                Route("GET", "/vendor/vis-network.min.js", self.get_vis_network),
                # -- POST --------------------------------------------------
                Route("POST", "/api/ingest/upload", self.post_ingest_upload),
                Route("POST", "/api/graph/merge", self.post_graph_merge),
                Route("POST", "/api/release/rollback", self.post_release_rollback),
                Route("POST", "/api/graph/query", self.post_graph_query),
                Route("POST", "/api/alignment/verify", self.post_alignment_verify),
                Route("POST", "/api/alignment/decision", self.post_alignment_decision),
                Route("POST", "/api/assertions/<rest...>", self.post_assertion_review),
                Route("POST", "/api/pipeline/execute", self.post_pipeline_execute),
                Route("GET", "/api/pipeline/events/<run_id>", self.get_pipeline_events),
                Route("POST", "/api/backup", self.post_backup),
            ]
        )

    # ==================================================================
    # GET handlers
    # ==================================================================

    def get_health(self, ctx: RequestContext) -> Response:
        h = healthcheck()
        return Response.json(
            {
                "status": h.status,
                "version": h.version,
                "component": h.component,
                "storage": "sqlite",
                "embeddings": "pluggable",
            }
        )

    def get_embeddings_status(self, ctx: RequestContext) -> Response:
        from infrastructure.embeddings.protocol import EmbeddingProviderUnavailableError
        from infrastructure.embeddings.resolver import get_embedding_provider

        try:
            provider = get_embedding_provider()
            avail = provider.is_available()
            return Response.json(
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
            return Response.json(
                {
                    "status": "unavailable",
                    "provider": "none",
                    "model_id": "BAAI/bge-large-en-v1.5",
                    "dimensions": 1024,
                    "message": str(e),
                }
            )

    def get_ollama_models(self, ctx: RequestContext) -> Response:
        models = ollama_client.fetch_ollama_models()
        if models:
            return Response.json({"status": "success", "models": models})
        return Response.json(
            {
                "status": "unavailable",
                "models": [],
                "message": "Ollama service is not running or no models are installed.",
            }
        )

    def get_benchmarks(self, ctx: RequestContext) -> Response:
        force_refresh = ctx.query_flag("refresh", "false").lower() in ("true", "1")
        now = time.time()

        with self._benchmark_lock:
            if (
                not force_refresh
                and self._benchmark_cache is not None
                and (now - self._benchmark_cache_time) < _BENCHMARK_CACHE_TTL_SEC
            ):
                return Response.json(
                    {"status": "success", "metrics": self._benchmark_cache, "cached": True}
                )
            try:
                benchmarker = SystemBenchmarker()
                res = benchmarker.run_benchmarks()
                metrics_dict = res.model_dump(mode="json")
                self._benchmark_cache = metrics_dict
                self._benchmark_cache_time = now
                return Response.json(
                    {"status": "success", "metrics": metrics_dict, "cached": False}
                )
            except Exception as exc:
                logger.error("Benchmark execution failed: %s", exc, exc_info=True)
                return Response.error(f"Benchmark execution failed: {exc}", status=500)

    def get_sample_data_list(self, ctx: RequestContext) -> Response:
        return Response.json({"status": "success", "samples": _SAMPLE_CATALOG})

    def get_sample_data_file(self, ctx: RequestContext) -> Response:
        sample_id = ctx.params["rest"].strip()
        file_name = _SAMPLE_FILE_MAP.get(sample_id)
        if not file_name:
            return Response.error(f"Sample dataset '{sample_id}' not found.", status=404)

        sample_path = TESTDATA_DIR / file_name
        if not sample_path.is_file():
            return Response.error(f"Sample file '{file_name}' does not exist on disk.", status=404)

        ext = sample_path.suffix.lower()
        fmt = "turtle" if ext == ".ttl" else ("jsonld" if ext in (".json", ".jsonld") else "csv")
        content = sample_path.read_text(encoding="utf-8")
        return Response.json(
            {
                "status": "success",
                "sample_id": sample_id,
                "file_name": file_name,
                "format": fmt,
                "content": content,
            }
        )

    def get_fusion_configs(self, ctx: RequestContext) -> Response:
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
        return Response.json({"status": "success", "presets": presets_summary})

    def get_graph_data(self, ctx: RequestContext) -> Response:
        active_graph = self.graph.get_active()
        return Response.json(
            {"status": "success", "nodes": active_graph["nodes"], "edges": active_graph["edges"]}
        )

    def get_entities_by_type(self, ctx: RequestContext) -> Response:
        target_type = ctx.query_flag("type", "").lower().strip()
        active_graph = self.graph.get_active()
        nodes = [
            n
            for n in active_graph.get("nodes", [])
            if not target_type
            or target_type in str(n.get("type", "")).lower()
            or target_type in str(n.get("kind", "")).lower()
        ]
        return Response.json({"status": "success", "entities": nodes, "count": len(nodes)})

    def get_diseases_detected(self, ctx: RequestContext) -> Response:
        try:
            try:
                from applications.drug_repurposing import extract_detected_diseases

                diseases = extract_detected_diseases(self.graph.get_active(), self.assertions)
            except ImportError:
                diseases = []
            return Response.json(
                {"status": "success", "diseases": diseases, "count": len(diseases)}
            )
        except Exception as exc:
            return Response.error(f"Disease detection error: {exc}", status=500)

    def get_active_projections(self, ctx: RequestContext) -> Response:
        try:
            active_records = self.projections.get_all_active()
            return Response.json(
                {
                    "status": "success",
                    "active_projections": [r.model_dump(mode="json") for r in active_records],
                    "count": len(active_records),
                }
            )
        except Exception as exc:
            return Response.error(f"Projection query error: {exc}", status=500)

    def get_release(self, ctx: RequestContext) -> Response:
        release_id = ctx.params["release_id"]
        release = self.graph.get_release(release_id)
        if release is None:
            return Response.error("Release not found.", status=404)
        return Response.json({"status": "success", "release": release})

    def get_artifact(self, ctx: RequestContext) -> Response:
        subpath = ctx.params["rest"]
        if subpath.endswith("/verify"):
            artifact_id_str = urllib.parse.unquote(subpath.removesuffix("/verify"))
            art_id = self._parse_artifact_id(artifact_id_str)
            try:
                self.artifacts.verify_integrity(art_id)
                return Response.json(
                    {
                        "status": "ok",
                        "artifact_id": art_id.canonical,
                        "message": "Integrity verified",
                    }
                )
            except KeyError:
                return Response.error("Artifact not found.", status=404)
            except ArtifactIntegrityError as exc:
                return Response.json(
                    {"status": "fail", "error": "digest mismatch", "detail": str(exc)}, status=409
                )

        artifact_id_str = urllib.parse.unquote(subpath)
        art_id = self._parse_artifact_id(artifact_id_str)
        artifact = self.artifacts.get(art_id)
        if artifact is None:
            artifact = self.artifacts.by_sha256(artifact_id_str)
        if artifact is None:
            return Response.error("Artifact not found.", status=404)
        return Response.json({"status": "success", "artifact": artifact.model_dump(mode="json")})

    @staticmethod
    def _parse_artifact_id(artifact_id_str: str) -> Identifier:
        if ":" in artifact_id_str:
            return Identifier.parse(artifact_id_str)
        return Identifier(namespace="artifact", value=artifact_id_str)

    def get_assertion(self, ctx: RequestContext) -> Response:
        assertion_id_str = ctx.params["assertion_id"]
        ass_id = self.safe_identifier(assertion_id_str, default_ns="assertion")
        assertion = self.assertions.get_assertion(ass_id)
        if assertion is None:
            return Response.error("Assertion not found.", status=404)
        events = self.assertions.get_state_events(assertion.id)
        current_st = events[-1].to_state.value if events else assertion.status_at_creation.value
        return Response.json(
            {
                "status": "success",
                "assertion": assertion.model_dump(mode="json"),
                "assertion_id": assertion.id.canonical,
                "current_state": current_st,
                "events": [e.model_dump(mode="json") for e in events],
            }
        )

    def get_entity_assertions(self, ctx: RequestContext) -> Response:
        """Full provenance trail for one entity: assertions + state events."""
        try:
            entity_raw = urllib.parse.unquote(ctx.params["rest"])
            if entity_raw.endswith("/assertions"):
                entity_raw = entity_raw.removesuffix("/assertions")
            if not entity_raw:
                return Response.error("Missing entity identifier in path.", status=400)
            # Graph node ids are bare values ("bio:INS" style); the store
            # matches canonical and bare forms, so pass the raw id through.
            assertions = self.assertions.get_assertions_by_entity(entity_raw, limit=200)
            trails: list[dict[str, Any]] = []
            for assertion in assertions:
                events = self.assertions.get_state_events(assertion.id)
                current_state = (
                    events[-1].to_state.value if events else assertion.status_at_creation.value
                )
                trails.append(
                    {
                        "assertion": assertion.model_dump(mode="json"),
                        "assertion_id": assertion.id.canonical,
                        "current_state": current_state,
                        "events": [e.model_dump(mode="json") for e in events],
                    }
                )
            return Response.json(
                {
                    "status": "success",
                    "entity": entity_raw,
                    "count": len(trails),
                    "trails": trails,
                }
            )
        except Exception as exc:
            return Response.error(f"Entity assertion query failed: {exc}", status=500)

    def get_release_list(self, ctx: RequestContext) -> Response:
        """Release timeline for the time-travel UI, oldest first."""
        try:
            releases = self.graph.list_releases()
            return Response.json(
                {"status": "success", "releases": releases, "count": len(releases)}
            )
        except Exception as exc:
            return Response.error(f"Release listing failed: {exc}", status=500)

    def get_graph_diff(self, ctx: RequestContext) -> Response:
        """Triple-level diff between two persisted release snapshots."""
        try:
            from_id = ctx.query_flag("from", "").strip()
            to_id = ctx.query_flag("to", "").strip()
            if not from_id or not to_id:
                return Response.error(
                    "Missing required query params: 'from' and 'to' release IDs.", status=400
                )
            if from_id == to_id:
                return Response.error("'from' and 'to' must name different releases.", status=400)

            from_release = self.graph.get_release(from_id)
            to_release = self.graph.get_release(to_id)
            if from_release is None:
                return Response.error(f"Release not found: {from_id}", status=404)
            if to_release is None:
                return Response.error(f"Release not found: {to_id}", status=404)

            def edge_key(e: dict[str, Any]) -> tuple[str, str, str]:
                return (str(e.get("from", "")), str(e.get("label", "")), str(e.get("to", "")))

            from_edges = {edge_key(e): e for e in from_release.get("edges", []) or []}
            to_edges = {edge_key(e): e for e in to_release.get("edges", []) or []}
            added_keys = to_edges.keys() - from_edges.keys()
            removed_keys = from_edges.keys() - to_edges.keys()

            from_nodes = {str(n.get("id")): n for n in from_release.get("nodes", []) or []}
            to_nodes = {str(n.get("id")): n for n in to_release.get("nodes", []) or []}
            node_ids_touched = {k for key in added_keys | removed_keys for k in (key[0], key[2])}

            def node_payload(n: dict[str, Any] | None) -> dict[str, Any] | None:
                if n is None:
                    return None
                return {"id": n.get("id"), "label": n.get("label"), "group": n.get("group")}

            return Response.json(
                {
                    "status": "success",
                    "from_release": from_id,
                    "to_release": to_id,
                    "added_edges": [to_edges[k] for k in sorted(added_keys)],
                    "removed_edges": [from_edges[k] for k in sorted(removed_keys)],
                    "added_nodes": [
                        node_payload(to_nodes[i])
                        for i in sorted(node_ids_touched - from_nodes.keys())
                        if to_nodes.get(i)
                    ],
                    "removed_nodes": [
                        node_payload(from_nodes[i])
                        for i in sorted(node_ids_touched - to_nodes.keys())
                        if from_nodes.get(i)
                    ],
                    "summary": {
                        "added_edges": len(added_keys),
                        "removed_edges": len(removed_keys),
                        "added_nodes": len(node_ids_touched - from_nodes.keys()),
                        "removed_nodes": len(node_ids_touched - to_nodes.keys()),
                    },
                }
            )
        except Exception as exc:
            return Response.error(f"Graph diff failed: {exc}", status=500)

    # ------------------------------------------------------------------
    # Real-time graph intelligence handlers live in the
    # GraphIntelligenceMixin (infrastructure/api/graph_intelligence.py):
    # semantic search + BFS/DFS traversal over the live active graph.
    # ------------------------------------------------------------------

    def get_alignment_candidates(self, ctx: RequestContext) -> Response:
        active_graph = self.graph.get_active()
        nodes = active_graph.get("nodes", [])
        edges = active_graph.get("edges", [])

        candidates_list: list[dict[str, Any]] = []

        edge_map: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            s = str(edge.get("from", ""))
            t = str(edge.get("to", ""))
            edge_map.setdefault(s, []).append(edge)
            edge_map.setdefault(t, []).append(edge)

        for i, n1 in enumerate(nodes):
            for n2 in nodes[i + 1 :]:
                lbl1 = str(n1.get("label", n1.get("id", ""))).strip().lower()
                lbl2 = str(n2.get("label", n2.get("id", ""))).strip().lower()
                if not lbl1 or not lbl2 or lbl1 == lbl2:
                    continue
                toks1 = set(lbl1.split())
                toks2 = set(lbl2.split())
                has_overlap = bool(toks1.intersection(toks2)) or (
                    len(lbl1) >= 3 and len(lbl2) >= 3 and (lbl1 in lbl2 or lbl2 in lbl1)
                )
                if has_overlap:
                    score = 0.88 if (lbl1 in lbl2 or lbl2 in lbl1) else 0.78
                    candidates_list.append(self._build_candidate(n1, n2, score, edge_map))

        if len(candidates_list) < 3:
            candidates_list.extend(_CURATED_ALIGNMENT_PAIRS)

        return Response.json({"status": "success", "candidates": candidates_list})

    @staticmethod
    def _build_candidate(
        n1: dict[str, Any],
        n2: dict[str, Any],
        score: float,
        edge_map: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        s_id = str(n1.get("id"))
        t_id = str(n2.get("id"))
        s_edges = edge_map.get(s_id, [])
        t_edges = edge_map.get(t_id, [])
        return {
            "id": f"cand_{n1.get('id')}_{n2.get('id')}",
            "source": {
                "id": s_id,
                "label": str(n1.get("label", n1.get("id"))),
                "group": str(n1.get("group", "Entity")),
                "edges_count": len(s_edges),
                "neighbors": [
                    {
                        "id": str(e["to"] if str(e.get("from")) == s_id else e.get("from")),
                        "label": str(e.get("label", "relates_to")),
                        "rel": str(e.get("label", "relates_to")),
                        "group": "Neighbor",
                    }
                    for e in s_edges[:6]
                ],
            },
            "target": {
                "id": t_id,
                "label": str(n2.get("label", n2.get("id"))),
                "group": str(n2.get("group", "Candidate")),
                "edges_count": len(t_edges),
                "neighbors": [
                    {
                        "id": str(e["to"] if str(e.get("from")) == t_id else e.get("from")),
                        "label": str(e.get("label", "relates_to")),
                        "rel": str(e.get("label", "relates_to")),
                        "group": "Neighbor",
                    }
                    for e in t_edges[:6]
                ],
            },
            "similarity": score,
            "status": "BORDERLINE",
            "source_graph": "Graph A",
            "target_graph": "Graph B",
        }

    # -- Static files ----------------------------------------------------

    def get_index(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "index.html"), "text/html; charset=utf-8")

    def get_alignment_studio(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "alignment_studio.html"), "text/html; charset=utf-8")

    def get_alignment_studio_css(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "alignment_studio.css"), "text/css")

    def get_alignment_studio_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "alignment_studio.js"), "application/javascript")

    def get_auth_client_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "auth_client.js"), "application/javascript")

    def get_theme_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "theme.js"), "application/javascript")

    def get_boot_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "boot.js"), "application/javascript")

    def get_graph_preview_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "graph_preview.js"), "application/javascript")

    def get_lineage_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "lineage.js"), "application/javascript")

    def get_timetravel_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "timetravel.js"), "application/javascript")

    def get_sandbox_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "sandbox.js"), "application/javascript")

    def get_canvas_layout_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "canvas_layout.js"), "application/javascript")

    def get_styles(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "styles.css"), "text/css")

    def get_app_js(self, ctx: RequestContext) -> Response:
        return Response.file(str(UI_DIR / "app.js"), "application/javascript")

    def get_vis_network(self, ctx: RequestContext) -> Response:
        # Vendored, same-origin: replaces the unpkg CDN script (no SRI,
        # arbitrary-JS-on-CDN-compromise risk) — served only from our whitelist.
        return Response.file(
            str(UI_DIR / "vendor" / "vis-network.min.js"), "application/javascript"
        )

    # ==================================================================
    # POST handlers
    # ==================================================================

    def post_ingest_upload(self, ctx: RequestContext) -> Response:
        try:
            data = ctx.json()
            content_str = data.get("content", "")
            file_name = data.get("file_name", "dataset.ttl")
            format_type = data.get("format", "turtle")

            service = GraphFusionService()
            activity_id = Identifier(namespace="ACT", value="act_ingest_upload")
            graph_id = Identifier(namespace="graph", value="uploaded_kg")
            assertions = service.parse_content_to_assertions(
                str(content_str), str(format_type), graph_id, activity_id
            )

            # Persist raw artifact blob. A sentinel release row is created
            # first so the artifacts FK (source_release_id → releases) holds.
            ingest_release_id = "upload_transient"
            if self.graph.get_release(ingest_release_id) is None:
                self.graph.save_release(
                    ingest_release_id,
                    {"type": "transient_upload", "created_at": datetime.now(UTC).isoformat()},
                )
            artifact = self.artifacts.store(
                content=str(content_str).encode("utf-8"),
                source_release_id=Identifier(namespace="release", value=ingest_release_id),
                media_type=f"text/{format_type}",
                name=str(file_name),
                retrieved_at=datetime.now(UTC),
            )

            # Persist parsed assertions with lineage.
            if assertions:
                self.assertions.persist_batch(list(assertions), [])

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
                        "color": "#0969da",
                    }
                if o_val not in nodes_map:
                    nodes_map[o_val] = {
                        "id": o_val,
                        "label": o_val,
                        "group": "Entity",
                        "color": "#8250df",
                    }

                edges_list.append({"from": s_val, "to": o_val, "label": a.predicate})

            if nodes_map:
                self.graph.replace_active(list(nodes_map.values()), edges_list)

            records_count = len(assertions)
            return Response.json(
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
            return Response.error(f"Ingestion error: {exc}", status=400)

    def post_graph_merge(self, ctx: RequestContext) -> Response:
        try:
            data = ctx.json()
            graph_a_content = data.get("graph_a_content")
            if not graph_a_content or not str(graph_a_content).strip():
                return Response.error(
                    "Missing required field: 'graph_a_content' must not be empty.", status=400
                )

            graph_b_content = data.get("graph_b_content")
            if not graph_b_content or not str(graph_b_content).strip():
                return Response.error(
                    "Missing required field: 'graph_b_content' must not be empty.", status=400
                )

            graph_a_format = data.get("graph_a_format", "turtle")
            graph_b_format = data.get("graph_b_format", "csv")
            graph_a_id = data.get("graph_a_id", "graph_a")
            graph_b_id = data.get("graph_b_id", "graph_b")
            domain_preset = data.get("domain_preset", "general_agnostic")
            domain_config_data = data.get("domain_config", None)
            graph_a_hash = hashlib.sha256(str(graph_a_content).encode("utf-8")).hexdigest()
            graph_b_hash = hashlib.sha256(str(graph_b_content).encode("utf-8")).hexdigest()
            logger.info(
                "[API Ingest PHI-Safe Log] Graph A: fmt=%s, bytes=%d, sha256=%s",
                graph_a_format,
                len(str(graph_a_content)),
                graph_a_hash,
            )
            logger.info(
                "[API Ingest PHI-Safe Log] Graph B: fmt=%s, bytes=%d, sha256=%s",
                graph_b_format,
                len(str(graph_b_content)),
                graph_b_hash,
            )

            conflict_mode_str = data.get("conflict_mode", "conflict_preserve")
            mode = (
                ConflictMode(conflict_mode_str)
                if conflict_mode_str in [m.value for m in ConflictMode]
                else ConflictMode.CONFLICT_PRESERVE
            )

            fusion_req = GraphFusionRequest(
                graph_a_id=str(graph_a_id),
                graph_b_id=str(graph_b_id),
                graph_a_content=str(graph_a_content),
                graph_a_format=str(graph_a_format),
                graph_b_content=str(graph_b_content),
                graph_b_format=str(graph_b_format),
                conflict_mode=mode,
                domain_preset=str(domain_preset),
                domain_config=domain_config_data,
            )

            service = GraphFusionService()
            fusion_res = service.execute_fusion(fusion_req)
            res_dict = fusion_res.model_dump(mode="json")

            # What-If Sandbox: dry_run fuses for real (deterministic engine)
            # but persists nothing — no release, no assertions, no artifacts,
            # no active-graph replacement. The response reports counters only.
            if bool(data.get("dry_run", False)):
                nodes_count = len(res_dict.get("nodes", []) or [])
                edges_count = len(res_dict.get("edges", []) or [])
                conflicts = (res_dict.get("fusion_run", {}) or {}).get("conflicts_flagged")
                return Response.json(
                    {
                        "status": "success",
                        "dry_run": True,
                        "summary": {
                            "nodes": nodes_count,
                            "edges": edges_count,
                            "assertions": len(
                                getattr(fusion_res, "reconciled_assertions", None)
                                or getattr(fusion_res, "assertions", None)
                                or ()
                            ),
                            "conflicts_flagged": conflicts,
                            "conflict_mode": str(mode.value),
                            "domain_preset": str(domain_preset),
                        },
                        "fusion": res_dict,
                    }
                )
            release_id = res_dict["fusion_run"]["result_release_id"]["value"]
            release_identifier = Identifier(namespace="release", value=release_id)

            raw_assertions = (
                getattr(fusion_res, "reconciled_assertions", None)
                or getattr(fusion_res, "assertions", None)
                or ()
            )
            assertion_ids_for_capstone = [a.id.canonical for a in raw_assertions]

            # Persist fused assertions with lineage FIRST so assertions exist.
            if raw_assertions:
                events: list[AssertionStateEvent] = []
                for a in raw_assertions:
                    ev = AssertionStateEvent(
                        event_id=Identifier(namespace="EVT", value=f"evt_{a.id.value}_rec"),
                        assertion_id=a.id,
                        from_state=None,
                        to_state=AssertionState.CANDIDATE,
                        agent_id=a.provenance.agent_id,
                        activity_id=a.provenance.activity_id,
                        policy_version=getattr(
                            fusion_res.fusion_run, "fusion_policy_version", "1.0.0"
                        ),
                        reason_code="FUSED_CANONICAL_ASSERTION",
                        timestamp=datetime.now(UTC),
                    )
                    events.append(ev)
                self.assertions.persist_batch(list(raw_assertions), events)

            # Persist the release (validates assertion_ids, creates the row).
            res_dict = self.graph.save_release(
                release_id,
                res_dict,
                assertion_ids=assertion_ids_for_capstone if assertion_ids_for_capstone else None,
            )

            if raw_assertions:
                self.assertions.link_release_assertions(release_id, assertion_ids_for_capstone)

            # Persist raw artifact blobs (graph A and B source content).
            release_ref = Identifier(namespace="release", value=release_id)
            artifact_a = self.artifacts.store(
                content=str(graph_a_content).encode("utf-8"),
                source_release_id=release_ref,
                media_type=f"text/{graph_a_format}",
                name=str(graph_a_id),
                retrieved_at=datetime.now(UTC),
            )
            artifact_b = self.artifacts.store(
                content=str(graph_b_content).encode("utf-8"),
                source_release_id=release_ref,
                media_type=f"text/{graph_b_format}",
                name=str(graph_b_id),
                retrieved_at=datetime.now(UTC),
            )
            artifact_ids = [artifact_a.id.canonical, artifact_b.id.canonical]

            release_manager = ReleaseManager()
            release_candidate = release_manager.create_release(
                release_id=release_identifier,
                version="1.0.0",
                created_at=datetime.fromisoformat(res_dict["fusion_run"]["created_at"]),
                manifest=ReleaseManifest(
                    plugins=(Identifier(namespace="domain", value=str(domain_preset)),),
                    lockfiles=LockfileSet(
                        ontology=Identifier(namespace="lock", value="ontology_unknown"),
                        runtime=Identifier(namespace="lock", value="python_runtime"),
                        reasoner=Identifier(namespace="lock", value="reasoner_unknown"),
                        projection=Identifier(namespace="lock", value="projection_pending"),
                    ),
                ),
            )
            self.graph.save_release_lifecycle(release_id, release_candidate.model_dump(mode="json"))

            # Update active graph with the newly fused release graph.
            if fusion_res.nodes:
                self.graph.replace_active(res_dict["nodes"], res_dict["edges"])

            return Response.json(
                {
                    "status": "success",
                    "fusion": res_dict,
                    "artifact_ids": artifact_ids,
                    "persisted_assertions": len(raw_assertions),
                }
            )
        except Exception as exc:
            logger.error("[Server Fusion Exception] %s", exc)
            return Response.error(f"Fusion error: {exc}", status=400)

    def post_release_rollback(self, ctx: RequestContext) -> Response:
        try:
            data = ctx.json()
            target_release_id = data.get("target_release_id")
            if target_release_id is not None:
                target_release_id = str(target_release_id).strip() or None

            # 1. Roll back GraphStore active graph snapshots.
            previous_graph = self.graph.rollback()

            # 2. Roll back Projections across active/registered backends.
            active_projections = self.projections.get_all_active()
            demoted_projections: list[str] = []
            restored_projections: list[dict[str, Any]] = []
            active_release_id: str | None = None

            backend_ids = {p.backend_id for p in active_projections}
            if not backend_ids:
                backend_ids = set(self.projections.get_known_backends()) or {"memory", "rdf"}

            rollback_errors: list[str] = []
            for b_id in sorted(backend_ids):
                demoted_rec, restored_rec = self.projections.rollback_projection(
                    b_id, target_release_id=target_release_id
                )
                if demoted_rec is not None:
                    demoted_projections.append(demoted_rec.projection_id)
                    if self.projection_registry.has(b_id):
                        try:
                            backend = self.projection_registry.get(b_id)
                            backend.rollback(demoted_rec.projection_id)
                        except Exception as exc:
                            err_msg = (
                                f"Backend '{b_id}' failed to rollback projection "
                                f"'{demoted_rec.projection_id}': {exc}"
                            )
                            logger.error(err_msg)
                            rollback_errors.append(err_msg)
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

            if rollback_errors:
                return Response.json(
                    {
                        "status": "error",
                        "message": "Projection backend rollback encountered errors: "
                        + "; ".join(rollback_errors),
                        "rollback_errors": rollback_errors,
                        "demoted_projections": demoted_projections,
                        "restored_projections": restored_projections,
                    },
                    status=500,
                )

            if previous_graph is None and not restored_projections:
                return Response.json(
                    {
                        "status": "unavailable",
                        "message": "No previous persisted release snapshot or projection is available.",
                    },
                    status=409,
                )

            restored_nodes = len(previous_graph["nodes"]) if previous_graph is not None else 0
            restored_edges = len(previous_graph["edges"]) if previous_graph is not None else 0

            return Response.json(
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
            return Response.error(f"Rollback error: {exc}", status=500)

    def post_graph_query(self, ctx: RequestContext) -> Response:
        try:
            data = ctx.json()
            query = str(data.get("query", "")).strip()
            if not query:
                return Response.error("Query string must not be empty.", status=400)

            model = str(data.get("model", "")).strip()
            if not model:
                return Response.error("Model parameter is required for graph query.", status=400)

            graph_context = ollama_client.build_graph_context(self.graph.get_active())
            llm_response = ollama_client.query_ollama_model(model, query, graph_context)

            return Response.json(
                {"status": "success", "query": query, "model_used": model, "answer": llm_response}
            )
        except Exception as exc:
            return Response.error(f"Query error: {exc}", status=503)

    def post_alignment_verify(self, ctx: RequestContext) -> Response:
        try:
            data = ctx.json()
            pair = data.get("pair", {})
            model = str(data.get("model", "llama3.1:8b-instruct-q8_0"))
            score = float(data.get("confidence", 0.88))

            active_graph = self.graph.get_active()
            all_nodes: list[dict[str, Any]] = active_graph.get("nodes", [])
            source_label = pair.get("source_id") or pair.get("source") or pair.get("source_label")
            target_label = pair.get("target_id") or pair.get("target") or pair.get("target_label")

            if not source_label or not target_label:
                return Response.error(
                    "Missing required entity labels in 'pair': both 'source' and 'target' "
                    "must be provided or identifiable from the graph.",
                    status=400,
                )

            source_ent = self._find_or_build_entity(all_nodes, source_label)
            target_ent = self._find_or_build_entity(all_nodes, target_label)
            candidate = CandidateMatch(
                source_entity=source_ent,
                candidate_entity=target_ent,
                ranking_score=score,
                ranking_method="vector_similarity",
                activity_id=Identifier(namespace="ACT", value="act_candidate_gen_1"),
            )

            verifier = Local8BVerifier(
                mock_generator=self._ollama_verify_adapter(str(model)), max_retries=1
            )
            v_resp, _ = verifier.verify(source_ent, candidate)
            res_dict = v_resp.model_dump(mode="json")
            res_dict["model_used"] = model
            if "MODEL_PROVIDER_UNAVAILABLE" in v_resp.reason_codes:
                return Response.json(
                    {
                        "status": "unavailable",
                        "verification": res_dict,
                        "message": f"Model provider is unavailable for '{model}'.",
                    },
                    status=503,
                )
            return Response.json({"status": "success", "verification": res_dict})
        except Exception as exc:
            import traceback

            tb = traceback.format_exc()
            return Response.json(
                {"status": "error", "message": f"Verification error: {exc}", "traceback": tb},
                status=400,
            )

    @staticmethod
    def _find_or_build_entity(all_nodes: list[dict[str, Any]], val_or_label: Any) -> Entity:
        val_str = str(val_or_label).strip()
        v_low = val_str.lower()
        for n in all_nodes:
            if str(n.get("id", "")).lower() == v_low or str(n.get("label", "")).lower() == v_low:
                node_id = str(n.get("id") or val_str)
                node_label = str(n.get("label") or node_id)
                c_id = n.get("canonical_id")
                if c_id:
                    return Entity(
                        id=ApplicationCore.safe_identifier(str(c_id)),
                        kind=EntityKind.CONCEPT,
                        label=node_label,
                    )
                return Entity(
                    id=ApplicationCore.safe_identifier(node_id),
                    kind=EntityKind.CONCEPT,
                    label=node_label,
                )
        return Entity(
            id=ApplicationCore.safe_identifier(val_str),
            kind=EntityKind.CONCEPT,
            label=val_str,
        )

    @staticmethod
    def _ollama_verify_adapter(model: str) -> Any:
        import os

        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

        def _ollama_adapter(context_str: str) -> str:
            prompt = (
                "You are a strict, deterministic Knowledge Graph entity alignment verifier.\n"
                "Evaluate if the source and candidate entities represent the same concept.\n\n"
                f"Context:\n{context_str}\n\n"
                "Respond ONLY with a JSON object in this exact schema:\n"
                '{"outcome": "ACCEPT", "confidence": 0.90, "reason_codes": ["SEMANTIC_MATCH"], "explanation": "Entities represent the same concept."}\n'
                "Valid outcomes: ACCEPT, REJECT, ABSTAIN.\n"
            )
            import json as _json
            import urllib.request as _ur

            payload = _json.dumps(
                {"model": model, "prompt": prompt, "format": "json", "stream": False}
            ).encode("utf-8")
            req = _ur.Request(
                f"{base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with _ur.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    result_data = _json.loads(resp.read().decode("utf-8"))
                    return str(result_data.get("response", ""))
            raise RuntimeError("Ollama returned empty response")

        return _ollama_adapter

    def post_alignment_decision(self, ctx: RequestContext) -> Response:
        try:
            data = ctx.json()
            src_val = str(data.get("source_entity") or data.get("source_id") or "")
            tgt_val = str(data.get("candidate_entity") or data.get("target_id") or "")
            decision_str = str(data.get("decision", "REVIEW")).upper()
            reason_str = str(data.get("reason", "Human domain expert alignment review"))
            agent_str = str(data.get("agent_id", "EXPERT_REVIEWER"))

            if any(k in decision_str for k in ("ACCEPT", "SAME", "PROMOTED", "APPROVE")):
                target_state = AssertionState.APPROVED
            elif any(k in decision_str for k in ("REJECT", "DIFFERENT")):
                target_state = AssertionState.REJECTED
            else:
                target_state = AssertionState.PROMOTION_REVIEW

            ass_id_raw = data.get("assertion_id")
            ass_id: Identifier | None = None
            if ass_id_raw:
                ass_id = self.safe_identifier(str(ass_id_raw), default_ns="ASSERT")
            else:
                active = self.graph.get_active()
                for edge_item in active.get("edges", []):
                    if edge_item.get("from") in (src_val, tgt_val) or edge_item.get("to") in (
                        src_val,
                        tgt_val,
                    ):
                        edge_ass = edge_item.get("assertion_id")
                        if edge_ass:
                            ass_id = self.safe_identifier(str(edge_ass), default_ns="ASSERT")
                            break
                if ass_id is None:
                    pair_hash = hashlib.sha256(f"{src_val}:{tgt_val}".encode()).hexdigest()[:16]
                    ass_id = Identifier(namespace="ASSERT", value=f"align_dec_{pair_hash}")

            current_state: AssertionState | None = None
            existing_assertion = self.assertions.get_assertion(ass_id)
            if existing_assertion:
                events = self.assertions.get_state_events(ass_id)
                current_state = (
                    events[-1].to_state if events else existing_assertion.status_at_creation
                )
            else:
                s_id = (
                    self.safe_identifier(src_val, default_ns="ENTITY")
                    if src_val
                    else Identifier(namespace="ENTITY", value="unknown_src")
                )
                t_id = (
                    self.safe_identifier(tgt_val, default_ns="ENTITY")
                    if tgt_val
                    else Identifier(namespace="ENTITY", value="unknown_tgt")
                )
                safe_agent_id = self.safe_identifier(agent_str, default_ns="AGENT")
                synth_assertion = Assertion(
                    id=ass_id,
                    subject=s_id,
                    predicate="same_as"
                    if target_state == AssertionState.APPROVED
                    else "different_from",
                    object=t_id,
                    provenance=Provenance(
                        agent_id=safe_agent_id,
                        activity_id=Identifier(namespace="ACT", value="act_alignment_decision"),
                        asserted_at=datetime.now(UTC),
                    ),
                    status_at_creation=AssertionState.CANDIDATE,
                )
                self.assertions.persist_batch([synth_assertion], [])
                current_state = AssertionState.CANDIDATE

            evt_id = Identifier(
                namespace="EVT",
                value=f"evt_dec_{hashlib.sha256(f'{ass_id.canonical}_{datetime.now(UTC).isoformat()}'.encode()).hexdigest()[:16]}",
            )
            evt = AssertionStateEvent(
                event_id=evt_id,
                assertion_id=ass_id,
                from_state=current_state,
                to_state=target_state,
                agent_id=self.safe_identifier(agent_str, default_ns="AGENT"),
                activity_id=Identifier(namespace="ACT", value="act_alignment_decision"),
                policy_version="1.0.0",
                reason_code=reason_str[:64],
                timestamp=datetime.now(UTC),
            )
            self.assertions.persist_state_event(evt)

            return Response.json(
                {
                    "status": "success",
                    "event_id": evt.event_id.canonical,
                    "assertion_id": ass_id.canonical,
                    "from_state": current_state.value if current_state else None,
                    "to_state": target_state.value,
                    "reason": reason_str,
                }
            )
        except Exception as exc:
            return Response.error(f"Alignment decision persistence failed: {exc}", status=400)

    def post_assertion_review(self, ctx: RequestContext) -> Response:
        try:
            subpath = ctx.params["rest"]
            if not subpath.endswith("/review"):
                return Response.not_found("Endpoint not found")
            ass_id_str = urllib.parse.unquote(subpath.removesuffix("/review"))
            ass_id = self.safe_identifier(ass_id_str, default_ns="ASSERT")
            assertion = self.assertions.get_assertion(ass_id)
            if assertion is None:
                return Response.error("Assertion not found.", status=404)

            data = ctx.json()
            decision_str = str(data.get("decision", "REVIEW")).upper()
            reason_str = str(data.get("reason", "Human assertion review"))
            agent_str = str(data.get("agent_id", "EXPERT_REVIEWER"))

            if any(k in decision_str for k in ("ACCEPT", "SAME", "PROMOTED", "APPROVE")):
                target_state = AssertionState.APPROVED
            elif any(k in decision_str for k in ("REJECT", "DIFFERENT")):
                target_state = AssertionState.REJECTED
            else:
                target_state = AssertionState.PROMOTION_REVIEW

            events = self.assertions.get_state_events(ass_id)
            current_state = events[-1].to_state if events else assertion.status_at_creation

            evt_id = Identifier(
                namespace="EVT",
                value=f"evt_rev_{hashlib.sha256(f'{ass_id.canonical}_{datetime.now(UTC).isoformat()}'.encode()).hexdigest()[:16]}",
            )
            evt = AssertionStateEvent(
                event_id=evt_id,
                assertion_id=ass_id,
                from_state=current_state,
                to_state=target_state,
                agent_id=self.safe_identifier(agent_str, default_ns="AGENT"),
                activity_id=Identifier(namespace="ACT", value="act_assertion_review"),
                policy_version="1.0.0",
                reason_code=reason_str[:64],
                timestamp=datetime.now(UTC),
            )
            self.assertions.append_state_event(evt)
            return Response.json(
                {
                    "status": "success",
                    "event_id": evt.event_id.canonical,
                    "assertion_id": ass_id.canonical,
                    "from_state": current_state.value,
                    "to_state": target_state.value,
                }
            )
        except Exception as exc:
            return Response.error(f"Assertion review failed: {exc}", status=400)

    def get_pipeline_events(self, ctx: RequestContext) -> Response:
        """SSE stream of live 13-stage pipeline telemetry for one run.

        The run is executed here (fail-closed, real services) and every
        stage transition is emitted as it happens. Connection closes when
        the pipeline finishes. Auth is enforced by the adapter like any
        mutating route, since this endpoint *causes* a release.
        """
        import json as _json
        import queue as _queue
        import threading as _threading

        run_id = ctx.params["run_id"]
        events: _queue.Queue[tuple[str, str]] = _queue.Queue()
        done = {"flag": False}
        result_holder: dict[str, Any] = {}

        def on_stage(stage: str, status: str, detail: dict[str, Any]) -> None:
            events.put((stage, status))

        def run_pipeline() -> None:
            # domain_pack arrives as a query param (EventSource can't POST).
            pack_name = str(ctx.query_flag("domain_pack", "")).strip()
            try:
                if not pack_name:
                    result_holder["error"] = "Missing required field: 'domain_pack'."
                else:
                    e2e = EndToEndReleasePipeline(
                        graph_store=self.graph,
                        artifact_store=self.artifacts,
                        assertion_store=self.assertions,
                        projection_store=self.projections,
                        data_source=self.data_source,
                    )
                    pack = self.get_domain_pack(pack_name)
                    result = e2e.execute_pipeline(
                        plugin_pack=pack, run_id=run_id, on_stage=on_stage
                    )
                    result_holder["result"] = result.model_dump(mode="json")
            except Exception as exc:
                result_holder["error"] = str(exc)
            finally:
                done["flag"] = True
                events.put(("__done__", "done"))

        worker = _threading.Thread(target=run_pipeline, daemon=True)
        worker.start()

        def sse_body() -> Any:
            yield "retry: 2000\n\n"
            while True:
                try:
                    stage, status = events.get(timeout=120)
                except Exception:
                    break
                if stage == "__done__":
                    payload = {"type": "complete", "result": result_holder.get("result")}
                    if "error" in result_holder:
                        payload = {"type": "error", "message": result_holder["error"]}
                    yield f"event: complete\ndata: {_json.dumps(payload)}\n\n"
                    break
                yield (
                    f"event: stage\ndata: {_json.dumps({'type': 'stage', 'stage': stage, 'status': status})}\n\n"
                )
            worker.join(timeout=5)

        return Response(status=200, sse=sse_body)

    def post_pipeline_execute(self, ctx: RequestContext) -> Response:
        try:
            data = ctx.json()
            pipeline_type = data.get("pipeline_type", "e2e_release")
            run_id = data.get("run_id", "run_web_001")

            if self.plugin_registry.workflows.has(str(pipeline_type)):
                workflow_fn = self.plugin_registry.workflows.get(str(pipeline_type))
                if workflow_fn is not None:
                    context = {
                        "graph_store": self.graph,
                        "artifact_store": self.artifacts,
                        "assertion_store": self.assertions,
                        "projection_store": self.projections,
                    }
                    wf_result = workflow_fn(data, context)
                    return Response.json(wf_result)

            e2e = EndToEndReleasePipeline(
                graph_store=self.graph,
                artifact_store=self.artifacts,
                assertion_store=self.assertions,
                projection_store=self.projections,
                data_source=self.data_source,
            )
            # Domain-neutral default: callers must name the domain pack
            # explicitly; the platform API never promotes one domain.
            pack_name = data.get("domain_pack")
            if not pack_name or not str(pack_name).strip():
                return Response.error(
                    "Missing required field: 'domain_pack'. Specify e.g. 'biomedical' or 'synthetic'.",
                    status=400,
                )
            pack = self.get_domain_pack(str(pack_name).strip())
            result = e2e.execute_pipeline(plugin_pack=pack, run_id=str(run_id))
            return Response.json(
                {
                    "status": "success",
                    "pipeline_type": "e2e_release",
                    "run_result": result.model_dump(mode="json"),
                }
            )
        except Exception as exc:
            return Response.error(f"Pipeline execution error: {exc}", status=400)

    def post_backup(self, ctx: RequestContext) -> Response:
        try:
            data = ctx.json()
            backup_dir_str = data.get("backup_dir", "backups")
            raw_path = Path(str(backup_dir_str))
            if raw_path.is_absolute():
                resolved_dir = raw_path.resolve()
            else:
                resolved_dir = (
                    (ROOT_DIR / "backups" / raw_path).resolve()
                    if not raw_path.parts or raw_path.parts[0] != "backups"
                    else (ROOT_DIR / raw_path).resolve()
                )

            allowed_roots = [
                (ROOT_DIR / "backups").resolve(),
                Path(tempfile.gettempdir()).resolve(),
            ]
            custom_base = os.getenv("HYBRID_KG_BACKUP_DIR")
            if custom_base:
                allowed_roots.append(Path(custom_base).resolve())

            is_allowed = False
            for base in allowed_roots:
                try:
                    resolved_dir.relative_to(base)
                    is_allowed = True
                    break
                except ValueError:
                    continue

            if not is_allowed:
                return Response.error(
                    "Invalid backup directory: path traversal detected or path outside "
                    "allowed backup directory.",
                    status=400,
                )

            resolved_dir.mkdir(parents=True, exist_ok=True)
            timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%SZ")
            backup_filename = f"hybrid_kg_backup_{timestamp_str}.sqlite3"
            backup_path = resolved_dir / backup_filename
            backup_database(self.graph.database_path, backup_path)
            is_valid = verify_backup(backup_path)
            if not is_valid:
                return Response.error("Backup integrity verification failed.", status=500)
            return Response.json(
                {
                    "status": "success",
                    "backup_path": str(backup_path),
                    "verified": True,
                }
            )
        except Exception as exc:
            return Response.error(f"Backup failed: {exc}", status=500)
