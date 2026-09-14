"""ChEMBL Biomedical Source Adapter."""

from __future__ import annotations

import json

from core.identifiers.identifier import Identifier
from core.resources.source_release import SourceRelease
from plugins.biomedical.adapters.observation import SourceObservation
from sdk.source_adapter import FetchResult


class ChEMBLSourceAdapter:
    """Source adapter for ChEMBL bioactive molecules and bioactivity data."""

    def fetch(self, release: SourceRelease) -> list[FetchResult]:
        return [
            FetchResult(
                name="chembl_molecule.json",
                media_type="application/json",
                content=b'{"molecule_chembl_id":"CHEMBL1431","pref_name":"METFORMIN"}',
            )
        ]

    def parse_observations(
        self, release: SourceRelease, fetch_result: FetchResult
    ) -> list[SourceObservation]:
        doc = json.loads(fetch_result.content.decode("utf-8"))
        raw_id = doc.get("molecule_chembl_id", "")
        norm_id = Identifier(namespace="CHEMBL", value=raw_id)
        obs = SourceObservation.create(
            source_id="chembl",
            source_release_id=release.id.value if hasattr(release, "id") else "chembl_rel_1",
            raw_record=doc,
            normalized_id=norm_id,
        )
        return [obs]
