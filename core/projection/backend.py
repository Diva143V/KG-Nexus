"""ProjectionBackend: the generic contract every projection backend implements.

This interface intentionally contains no backend-specific concepts: no graph
database, no graph query language, no search engine, no vector store, no
columnar file format, and no database-specific node/edge models. A backend is
*any* downstream projection that Core can manage without knowing which it is.
"""

from __future__ import annotations

from contracts.projections import ProjectionBackend

__all__ = ["ProjectionBackend"]
