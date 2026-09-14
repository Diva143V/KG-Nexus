"""UniProt Biomedical Source Adapter."""

from __future__ import annotations

import json

from core.identifiers.identifier import Identifier
from core.resources.source_release import SourceRelease
from plugins.biomedical.adapters.observation import SourceObservation
from sdk.source_adapter import FetchResult


class UniProtSourceAdapter:
    """Source adapter for UniProt protein records."""

    def fetch(self, release: SourceRelease) -> list[FetchResult]:
        return [
            FetchResult(
                name="uniprot_sprot.json",
                media_type="application/json",
                content=b'{"primaryAccession":"P01308","uniProtkbId":"INS_HUMAN"}',
            )
        ]

    def parse_observations(
        self, release: SourceRelease, fetch_result: FetchResult
    ) -> list[SourceObservation]:
        doc = json.loads(fetch_result.content.decode("utf-8"))
        raw_id = doc.get("primaryAccession", "")
        norm_id = Identifier(namespace="UniProtKB", value=raw_id)
        obs = SourceObservation.create(
            source_id="uniprot",
            source_release_id=release.id.value if hasattr(release, "id") else "uniprot_rel_1",
            raw_record=doc,
            normalized_id=norm_id,
        )
        return [obs]
