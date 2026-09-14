"""Knowledge Graph Fusion Subsystem."""

from core.fusion.models import (
    ConflictMode,
    FusionRun,
    GraphFusionRequest,
    GraphFusionResult,
)
from core.fusion.service import GraphFusionService
from core.fusion.source_aligner import (
    AlignedSourcePair,
    SourceAligner,
    SourceAlignmentResult,
)

__all__ = [
    "AlignedSourcePair",
    "ConflictMode",
    "FusionRun",
    "GraphFusionRequest",
    "GraphFusionResult",
    "GraphFusionService",
    "SourceAligner",
    "SourceAlignmentResult",
]
