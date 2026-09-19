"""HuggingFace / Sentence-Transformers Embedding Provider.

Executes real in-process neural semantic embeddings using HuggingFace models
(e.g., BAAI/bge-large-en-v1.5, PubMedBERT, BioLinkBERT, BioBERT).
"""

from __future__ import annotations

import threading
from typing import Any

from infrastructure.embeddings.protocol import (
    EmbeddingModelMetadata,
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
)

_CACHE_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, Any] = {}


class HuggingFaceEmbeddingProvider(EmbeddingProvider):
    """Loads and runs HuggingFace models in-process via sentence-transformers."""

    def __init__(
        self,
        model_id: str = "BAAI/bge-large-en-v1.5",
        device: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._dimensions: int | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider_type(self) -> str:
        return "huggingface"

    @property
    def dimensions(self) -> int:
        if self._dimensions is not None:
            return self._dimensions
        model = self._get_model()
        if model is not None:
            dim_getter = getattr(model, "get_embedding_dimension", None) or getattr(
                model, "get_sentence_embedding_dimension", None
            )
            dim = dim_getter() if callable(dim_getter) else None
            if isinstance(dim, int):
                self._dimensions = dim
                return self._dimensions
        return 1024

    def is_available(self) -> bool:
        """Check if sentence-transformers is installed and importable."""
        try:
            import sentence_transformers  # noqa: F401

            return True
        except ImportError:
            return False

    def _get_model(self) -> Any:
        with _CACHE_LOCK:
            if self._model_id in _MODEL_CACHE:
                return _MODEL_CACHE[self._model_id]

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise EmbeddingProviderUnavailableError(
                "sentence-transformers is not installed. Install with `pip install sentence-transformers`."
            ) from e

        try:
            model = SentenceTransformer(self._model_id, device=self._device)
            with _CACHE_LOCK:
                _MODEL_CACHE[self._model_id] = model
            dim_getter = getattr(model, "get_embedding_dimension", None) or getattr(
                model, "get_sentence_embedding_dimension", None
            )
            dim = dim_getter() if callable(dim_getter) else None
            if isinstance(dim, int):
                self._dimensions = dim
            return model
        except Exception as e:
            raise EmbeddingProviderUnavailableError(
                f"Failed to load HuggingFace embedding model '{self._model_id}': {e}"
            ) from e

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []

        model = self._get_model()
        try:
            # normalize_embeddings=True guarantees L2-normalized unit vectors
            embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            results: list[tuple[float, ...]] = []
            for row in embeddings:
                results.append(tuple(float(x) for x in row))
            if results and self._dimensions is None:
                self._dimensions = len(results[0])
            return results
        except Exception as e:
            raise EmbeddingProviderUnavailableError(
                f"Inference error with HuggingFace model '{self._model_id}': {e}"
            ) from e

    def get_metadata(self) -> EmbeddingModelMetadata:
        return EmbeddingModelMetadata(
            model_id=self._model_id,
            provider_type=self.provider_type,
            dimensions=self.dimensions,
            model_digest=f"huggingface:{self._model_id}",
            parameters={"device": self._device or "auto"},
        )
