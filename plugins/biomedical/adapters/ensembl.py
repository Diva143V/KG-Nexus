"""Ensembl Biomedical Source Adapter."""

from __future__ import annotations

import json

from core.identifiers.identifier import Identifier
from core.resources.source_release import SourceRelease
from plugins.biomedical.adapters.observation import SourceObservation
from sdk.source_adapter import FetchResult


class EnsemblSourceAdapter:
    """Source adapter for Ensembl genes and transcripts."""

    def fetch(self, release: SourceRelease) -> list[FetchResult]:
        return [
            FetchResult(
                name="ensembl_genes.json",
                media_type="application/json",
                content=b'{"id":"ENSG00000254647","display_name":"INS","species":"homo_sapiens"}',
            )
        ]

    def parse_observations(
        self, release: SourceRelease, fetch_result: FetchResult
    ) -> list[SourceObservation]:
        doc = json.loads(fetch_result.content.decode("utf-8"))
        raw_id = doc.get("id", "")
        norm_id = Identifier(namespace="ENSG", value=raw_id)
        obs = SourceObservation.create(
            source_id="ensembl",
            source_release_id=release.id.value if hasattr(release, "id") else "ensembl_rel_1",
            raw_record=doc,
            normalized_id=norm_id,
        )
        return [obs]
