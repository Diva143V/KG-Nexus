"""HGNC Biomedical Source Adapter."""

from __future__ import annotations

import json

from core.identifiers.identifier import Identifier
from core.resources.source_release import SourceRelease
from plugins.biomedical.adapters.observation import SourceObservation
from sdk.source_adapter import FetchResult


class HGNCSourceAdapter:
    """Source adapter for HGNC (Hugo Gene Nomenclature Committee)."""

    def fetch(self, release: SourceRelease) -> list[FetchResult]:
        return [
            FetchResult(
                name="hgnc_complete_set.json",
                media_type="application/json",
                content=b'{"response":{"docs":[{"hgnc_id":"HGNC:6018","symbol":"INS","name":"insulin"}]}}',
            )
        ]

    def parse_observations(
        self, release: SourceRelease, fetch_result: FetchResult
    ) -> list[SourceObservation]:
        data = json.loads(fetch_result.content.decode("utf-8"))
        docs = data.get("response", {}).get("docs", [])
        observations: list[SourceObservation] = []
        for doc in docs:
            raw_id = doc.get("hgnc_id", "")
            val = raw_id.split(":")[-1] if ":" in raw_id else raw_id
            norm_id = Identifier(namespace="HGNC", value=f"HGNC:{val}")
            obs = SourceObservation.create(
                source_id="hgnc",
                source_release_id=release.id.value if hasattr(release, "id") else "hgnc_rel_1",
                raw_record=doc,
                normalized_id=norm_id,
            )
            observations.append(obs)
        return observations
