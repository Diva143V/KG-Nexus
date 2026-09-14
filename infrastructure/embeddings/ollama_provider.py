"""Ollama Embedding Provider.

Communicates with local Ollama daemon via HTTP (`/api/embed` or `/api/embeddings`).
Zero extra Python dependencies; offloads heavy matrix operations to the local daemon.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from infrastructure.embeddings.protocol import (
    EmbeddingModelMetadata,
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embedding provider that calls a local or remote Ollama HTTP server."""

    def __init__(
        self,
        model_id: str = "BAAI/bge-large-en-v1.5",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 30.0,
    ) -> None:
        self._model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._detected_dimensions: int | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider_type(self) -> str:
        return "ollama"

    @property
    def dimensions(self) -> int:
        return self._detected_dimensions or 1024

    def is_available(self) -> bool:
        """Check if Ollama is running and has the model available."""
        try:
            req = urllib.request.Request(
                f"{self._base_url}/api/tags", headers={"User-Agent": "HybridKG/1.0"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name", "") for m in data.get("models", [])]
                    # Check exact or prefix match (e.g. bge-large vs bge-large:latest)
                    norm_target = self._model_id.lower().split("/")[-1].split(":")[0]
                    return any(norm_target in m.lower() for m in models) or len(models) > 0
        except Exception:
            return False
        return False

    def _normalize_vector(self, vec: list[float]) -> tuple[float, ...]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return tuple(vec)
        return tuple(v / norm for v in vec)

    def _embed_via_embed_endpoint(self, texts: list[str]) -> list[tuple[float, ...]] | None:
        """Attempt modern `/api/embed` batch endpoint."""
        url = f"{self._base_url}/api/embed"
        payload = json.dumps({"model": self._model_id, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "HybridKG/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw_vectors = data.get("embeddings", [])
                    if raw_vectors and len(raw_vectors) == len(texts):
                        if not self._detected_dimensions and len(raw_vectors[0]) > 0:
                            self._detected_dimensions = len(raw_vectors[0])
                        return [self._normalize_vector(v) for v in raw_vectors]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # Endpoint not supported on older Ollama, fall back
            raise EmbeddingProviderUnavailableError(
                f"Ollama embedding request failed ({e.code}): {e.reason}"
            ) from e
        except Exception as e:
            raise EmbeddingProviderUnavailableError(
                f"Ollama service unreachable at {self._base_url}: {e}"
            ) from e
        return None

    def _embed_single(self, text: str) -> tuple[float, ...]:
        """Fallback to legacy `/api/embeddings` single prompt endpoint."""
        url = f"{self._base_url}/api/embeddings"
        payload = json.dumps({"model": self._model_id, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "HybridKG/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw_vec = data.get("embedding", [])
                    if not raw_vec:
                        raise EmbeddingProviderUnavailableError(
                            f"Ollama returned empty embedding for model '{self._model_id}'."
                        )
                    if not self._detected_dimensions:
                        self._detected_dimensions = len(raw_vec)
                    return self._normalize_vector(raw_vec)
        except Exception as e:
            raise EmbeddingProviderUnavailableError(
                f"Failed to obtain embedding from Ollama model '{self._model_id}': {e}"
            ) from e
        raise EmbeddingProviderUnavailableError("Ollama failed to produce embedding.")

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []

        # Try batch /api/embed first
        batch_res = self._embed_via_embed_endpoint(texts)
        if batch_res is not None:
            return batch_res

        # Fall back to iterating /api/embeddings
        return [self._embed_single(t) for t in texts]

    def get_metadata(self) -> EmbeddingModelMetadata:
        return EmbeddingModelMetadata(
            model_id=self._model_id,
            provider_type=self.provider_type,
            dimensions=self.dimensions,
            model_digest=f"ollama:{self._model_id}",
            parameters={"base_url": self._base_url, "timeout": self._timeout},
        )
