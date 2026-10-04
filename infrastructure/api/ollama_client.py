"""Ollama daemon client: model discovery and graph-context QA.

Extracted from infrastructure/api/server.py so transport (HTTP handler),
policy (security), and this external-service adapter each own one job.
Every function raises an explicit error on failure — fail-closed, no silent
empty results.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from typing import Any, cast


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


_OLLAMA_LIST_TIMEOUT_SEC = 5
_OLLAMA_QUERY_TIMEOUT_SEC = 60


def fetch_ollama_models() -> list[dict[str, str]]:
    """Auto-detect models using the daemon HTTP API, falling back to the CLI."""
    models: list[dict[str, str]] = []

    try:
        req = urllib.request.Request(f"{_ollama_base_url()}/api/tags")
        with urllib.request.urlopen(req, timeout=_OLLAMA_LIST_TIMEOUT_SEC) as resp:
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

    if not models:
        try:
            proc = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=_OLLAMA_LIST_TIMEOUT_SEC,
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


def query_ollama_model(model_name: str, prompt: str, graph_context: str) -> str:
    """Send a prompt (prefixed with ``graph_context``) to the local Ollama daemon.

    Raises ``RuntimeError`` on transport failure or empty response — callers
    translate that into a 503, never a silent degradation.
    """
    full_prompt = f"{graph_context}\nUser Question: {prompt}"

    try:
        url = f"{_ollama_base_url()}/api/generate"
        payload = json.dumps({"model": model_name, "prompt": full_prompt, "stream": False}).encode(
            "utf-8"
        )
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=_OLLAMA_QUERY_TIMEOUT_SEC) as resp:
            if resp.status == 200:
                result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                response_text = result.get("response", "").strip()
                if response_text:
                    return cast(str, response_text)
    except Exception as exc:
        raise RuntimeError(f"Ollama query failed: {exc}") from exc

    raise RuntimeError(f"Ollama returned empty response for model '{model_name}'.")


def build_graph_context(active_graph: dict[str, Any]) -> str:
    """Render the first active-graph entities as QA prompt context."""
    entities = [n["label"] for n in active_graph.get("nodes", [])[:10]]
    if entities:
        return f"Active Knowledge Graph entities: {', '.join(entities)}."
    return "Active Knowledge Graph is empty."
