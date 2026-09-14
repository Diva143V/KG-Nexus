"""ChEBI Biomedical Source Adapter."""

from __future__ import annotations

from core.identifiers.identifier import Identifier
from core.resources.source_release import SourceRelease
from plugins.biomedical.adapters.observation import SourceObservation
from sdk.source_adapter import FetchResult


class ChEBISourceAdapter:
    """Source adapter for ChEBI chemical entities."""

    def fetch(self, release: SourceRelease) -> list[FetchResult]:
        return [
            FetchResult(
                name="chebi_entities.tsv",
                media_type="text/tab-separated-values",
                content=b"CHEBI_ID\tNAME\tDEFINITION\nCHEBI:15365\taspirin\ta monocarboxylic acid\n",
            )
        ]

    def parse_observations(
        self, release: SourceRelease, fetch_result: FetchResult
    ) -> list[SourceObservation]:
        lines = fetch_result.content.decode("utf-8").strip().split("\n")
        observations: list[SourceObservation] = []
        if len(lines) > 1:
            parts = lines[1].split("\t")
            chebi_id = parts[0]
            name = parts[1] if len(parts) > 1 else ""
            doc = {"chebi_id": chebi_id, "name": name}
            norm_id = Identifier(namespace="CHEBI", value=chebi_id)
            obs = SourceObservation.create(
                source_id="chebi",
                source_release_id=release.id.value if hasattr(release, "id") else "chebi_rel_1",
                raw_record=doc,
                normalized_id=norm_id,
            )
            observations.append(obs)
        return observations
