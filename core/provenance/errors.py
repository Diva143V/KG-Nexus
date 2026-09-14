"""Provenance and lineage error types."""


class ProvenanceError(Exception):
    """Base class for provenance failures."""


class IncompleteLineageError(ProvenanceError):
    """A derived assertion lacks required lineage for promotion."""


class UnresolvedReferenceError(ProvenanceError):
    """A lineage reference does not resolve to a registered record."""
