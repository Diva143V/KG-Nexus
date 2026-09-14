"""Tests for REST API Server and Ollama Model Discovery."""

import json
import threading
import time
import urllib.request

import pytest

from infrastructure.api import server as api_server
from infrastructure.api.server import create_server, fetch_ollama_models


@pytest.fixture(scope="module")
def server_url():
    """Start API server on ephemeral port for automated testing."""
    api_server.GRAPH_STORE.reset()
    server, active_port = create_server("127.0.0.1", 8088)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{active_port}"
    server.shutdown()


def test_ollama_model_discovery(monkeypatch):
    mock_models = [{"name": "llama3.1:8b", "size": "4.7 GB", "source": "ollama daemon"}]
    monkeypatch.setattr(api_server, "fetch_ollama_models", lambda: mock_models)
    monkeypatch.setattr("tests.test_ui_api.fetch_ollama_models", lambda: mock_models)
    models = fetch_ollama_models()
    assert isinstance(models, list)
    assert len(models) > 0
    assert "name" in models[0]


def test_api_ollama_models_endpoint(server_url):
    req = urllib.request.Request(f"{server_url}/api/ollama/models")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] in ("success", "unavailable")
        assert isinstance(data["models"], list)


def test_static_assets_serving(server_url):
    for asset_path in ["/", "/index.html", "/styles.css", "/app.js"]:
        req = urllib.request.Request(f"{server_url}{asset_path}")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            content = resp.read()
            assert len(content) > 100


def test_health_endpoint_reports_storage(server_url):
    req = urllib.request.Request(f"{server_url}/health")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
        assert data["storage"] == "sqlite"
        assert data["embeddings"] == "pluggable"


def test_api_embeddings_status_endpoint(server_url):
    req = urllib.request.Request(f"{server_url}/api/embeddings/status")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "status" in data
        assert "model_id" in data
        assert "dimensions" in data


def test_api_graph_data_endpoint_initially_empty(server_url):
    """Verify graph store remains empty on startup until real data is merged or ingested."""
    req = urllib.request.Request(f"{server_url}/api/graph/data")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert len(data["nodes"]) == 0
        assert len(data["edges"]) == 0


def test_api_graph_merge_validation_requires_inputs(server_url):
    """Verify /api/graph/merge rejects empty inputs with 400 Bad Request."""
    payload = json.dumps(
        {
            "graph_a_content": "",
            "graph_b_content": "",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/graph/merge",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400


def test_api_alignment_verify_endpoint(server_url):
    payload = json.dumps(
        {
            "pair": {"source": "HGNC:6018", "target": "P01308"},
            "confidence": 0.88,
            "model": "llama3.1:8b-instruct-q8_0",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/alignment/verify",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 503


def test_api_ingest_json_file(server_url):
    payload = json.dumps(
        {
            "file_name": "people.json",
            "format": "jsonld",
            "content": json.dumps(
                [{"subject": "synth:Alice", "predicate": "worksAt", "object": "synth:Acme"}]
            ),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/ingest/upload",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"


def test_api_fusion_json_files_and_populates_store(server_url):
    """Verify /api/graph/merge populates the graph store with real nodes and edges."""
    payload = json.dumps(
        {
            "graph_a_content": json.dumps(
                [{"subject": "synth:Alice", "predicate": "worksAt", "object": "synth:Acme"}]
            ),
            "graph_a_format": "jsonld",
            "graph_b_content": json.dumps(
                [{"subject": "synth:Bob", "predicate": "worksAt", "object": "synth:Acme"}]
            ),
            "graph_b_format": "jsonld",
            "conflict_mode": "conflict_preserve",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/graph/merge", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["fusion"]["fusion_run"]["fusion_run_id"] is not None
        assert len(data["fusion"]["nodes"]) > 0

    release_id = data["fusion"]["fusion_run"]["result_release_id"]["value"]
    release_req = urllib.request.Request(f"{server_url}/api/releases/{release_id}")
    with urllib.request.urlopen(release_req) as release_resp:
        release_data = json.loads(release_resp.read().decode("utf-8"))
        assert release_data["status"] == "success"
        assert release_data["release"]["fusion_run"]["result_release_id"]["value"] == release_id
        assert release_data["release"]["lifecycle"]["status"] == "candidate"

    # Now verify /api/graph/data has been populated
    req_data = urllib.request.Request(f"{server_url}/api/graph/data")
    with urllib.request.urlopen(req_data) as resp_data:
        assert resp_data.status == 200
        store_data = json.loads(resp_data.read().decode("utf-8"))
        assert store_data["status"] == "success"
        assert len(store_data["nodes"]) > 0
        assert len(store_data["edges"]) > 0


def test_api_release_rollback_restores_previous_graph(server_url):
    payload = json.dumps(
        {
            "graph_a_content": json.dumps(
                [{"subject": "synth:One", "predicate": "worksAt", "object": "synth:Org"}]
            ),
            "graph_a_format": "jsonld",
            "graph_b_content": json.dumps(
                [{"subject": "synth:Two", "predicate": "worksAt", "object": "synth:Org"}]
            ),
            "graph_b_format": "jsonld",
        }
    ).encode("utf-8")
    merge_req = urllib.request.Request(
        f"{server_url}/api/graph/merge",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(merge_req) as resp:
        assert resp.status == 200

    rollback_req = urllib.request.Request(
        f"{server_url}/api/release/rollback",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(rollback_req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["rollback"]["durability"] == "sqlite"


def test_identical_fusion_request_is_idempotent(server_url):
    payload = json.dumps(
        {
            "graph_a_content": json.dumps(
                [{"subject": "synth:Repeat", "predicate": "worksAt", "object": "synth:Org"}]
            ),
            "graph_a_format": "jsonld",
            "graph_b_content": json.dumps(
                [{"subject": "synth:Repeat2", "predicate": "worksAt", "object": "synth:Org"}]
            ),
            "graph_b_format": "jsonld",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{server_url}/api/graph/merge",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as first_response:
        first = json.loads(first_response.read().decode("utf-8"))
    with urllib.request.urlopen(request) as second_response:
        second = json.loads(second_response.read().decode("utf-8"))

    first_id = first["fusion"]["fusion_run"]["result_release_id"]["value"]
    second_id = second["fusion"]["fusion_run"]["result_release_id"]["value"]
    assert first_id == second_id


def test_api_graph_query_error_on_missing_prompt(server_url):
    """Verify /api/graph/query rejects missing prompt with 400 Bad Request."""
    payload = json.dumps({"prompt": ""}).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/graph/query",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400


def test_api_benchmarks_metrics_endpoint(server_url):
    """Verify /api/benchmarks/metrics returns authentic benchmark metrics from versioned dataset."""
    req = urllib.request.Request(f"{server_url}/api/benchmarks/metrics")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        metrics = data["metrics"]
        assert metrics["dataset"] == "biomedical_1.0.0"
        assert metrics["candidate_generation"]["recall_at_10"] > 0.80
        assert metrics["resolution"]["precision"] >= 0.70
        assert metrics["resolution"]["recall"] >= 0.80
        assert metrics["resolution"]["f1"] >= 0.75
        assert metrics["projection"]["rebuild_reproducible"] is True
        assert metrics["projection"]["build_time_ms"] > 0.0
        assert metrics["projection"]["reconciliation_time_ms"] > 0.0
        assert metrics["operations"]["rollback_time_ms"] > 0.0
        assert metrics["operations"]["endpoint_switch_time_ms"] > 0.0


def test_api_sample_data_list(server_url):
    """Verify /api/sample-data returns available sample datasets."""
    req = urllib.request.Request(f"{server_url}/api/sample-data")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert isinstance(data["samples"], list)
        assert len(data["samples"]) >= 3
        ids = [s["id"] for s in data["samples"]]
        assert "biomedical_sample_graph" in ids
        assert "drug_repurposing_graph" in ids


def test_api_sample_data_fetch(server_url):
    """Verify /api/sample-data/biomedical returns raw content and metadata."""
    req = urllib.request.Request(f"{server_url}/api/sample-data/biomedical")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["format"] == "turtle"
        assert "P01308" in data["content"]


def test_api_sample_data_not_found(server_url):
    """Verify 404 on nonexistent sample ID."""
    req = urllib.request.Request(f"{server_url}/api/sample-data/nonexistent_sample")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 404


def test_api_fusion_configs(server_url):
    """Verify /api/fusion/configs returns domain presets."""
    req = urllib.request.Request(f"{server_url}/api/fusion/configs")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert len(data["presets"]) >= 2
        preset_ids = [p["id"] for p in data["presets"]]
        assert "biomedical" in preset_ids


def test_api_backup_endpoint(server_url, tmp_path):
    """Verify /api/backup creates a verified database snapshot."""
    backup_dir = tmp_path / "test_backups"
    payload = json.dumps({"backup_dir": str(backup_dir)}).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/backup",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["verified"] is True
        assert "hybrid_kg_backup_" in data["backup_path"]


def test_api_drug_repurposing_pipeline_execution(server_url):
    """Verify /api/pipeline/execute with drug_repurposing returns valid hypotheses."""
    payload = json.dumps(
        {
            "pipeline_type": "drug_repurposing",
            "target_disease": "MONDO:0005148",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/api/pipeline/execute",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["pipeline_type"] == "drug_repurposing"
        assert "hypotheses" in data
        assert isinstance(data["hypotheses"], list)
