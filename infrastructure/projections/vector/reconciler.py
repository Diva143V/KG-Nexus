"""Vector projection reconciliation against the authoritative RDF release.

RDF is authoritative. The reconciler compares the stored vector projection
against the policy-derived expected projection and reports, in deterministic
string terms:

* missing / unexpected embedded items;
* transformed items (same item key, different digest);
* item counts per kind;
* whether the stored manifest matches the expected manifest.

Data loss is never silently accepted: any divergence is reported. Item
comparisons use the stored manifest and vectors as they actually landed, so
tampering or corruption surfaces instead of being masked by re-derivation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile
from infrastructure.projections.vector.builder import (
    VectorDataSource,
    VectorProjectionBuilder,
)
from infrastructure.projections.vector.manifest import VectorManifest
from infrastructure.projections.vector.store import (
    VectorProjectionStore,
    vector_candidate_name,
)
from infrastructure.projections.vector.writer import (
    manifest_bytes,
    try_items_from_bytes,
    try_manifest_from_bytes,
)


class VectorReconciliationReport(BaseModel):
    """Outcome of reconciling one vector projection against its release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    missing_items: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_items: tuple[str, ...] = Field(default_factory=tuple)
    transformed_items: tuple[str, ...] = Field(default_factory=tuple)
    item_counts: dict[str, int] = Field(default_factory=dict)
    manifest_matches: bool = True

    @property
    def reconciled(self) -> bool:
        """True when the projection matches the expected vector content."""
        return (
            not (self.missing_items or self.unexpected_items or self.transformed_items)
            and self.manifest_matches
        )


class VectorReconciler:
    """Reconciles stored vectors against the authoritative RDF release."""

    def __init__(
        self,
        *,
        store: VectorProjectionStore,
        data_source: VectorDataSource,
        builder: VectorProjectionBuilder | None = None,
    ) -> None:
        self._store = store
        self._data_source = data_source
        self._builder = builder or VectorProjectionBuilder(
            store=store,
            data_source=data_source,
        )

    def reconcile(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> VectorReconciliationReport:
        """Compare the stored vector projection against the expected one."""
        expected = self._builder.derive(release_id, profile)
        store_key = vector_candidate_name(projection_id)

        expected_items = {item.key: item.digest for item in expected.items}
        actual_items = self._stored_items(store_key)

        missing_items = sorted(expected_items.keys() - set(actual_items))
        unexpected_items = sorted(set(actual_items) - expected_items.keys())
        transformed_items = sorted(
            key
            for key in expected_items.keys() & set(actual_items)
            if expected_items[key] != actual_items[key]
        )

        stored_manifest = self._stored_manifest(store_key)
        manifest_matches = stored_manifest is not None and manifest_bytes(
            stored_manifest
        ) == manifest_bytes(expected.manifest)

        item_counts: dict[str, int] = {}
        for kind in self._stored_kinds(store_key).values():
            item_counts[kind] = item_counts.get(kind, 0) + 1

        return VectorReconciliationReport(
            projection_id=projection_id,
            release_id=release_id,
            missing_items=tuple(missing_items),
            unexpected_items=tuple(unexpected_items),
            transformed_items=tuple(transformed_items),
            item_counts=item_counts,
            manifest_matches=manifest_matches,
        )

    def _stored_items(self, store_key: str) -> dict[str, str]:
        data = self._store.read_dataset(store_key, "vectors")
        if data is None:
            return {}
        items = try_items_from_bytes(data)
        if items is None:
            return {}
        return {item.key: item.digest for item in items}

    def _stored_manifest(self, store_key: str) -> VectorManifest | None:
        data = self._store.read_dataset(store_key, "manifest")
        if data is None:
            return None
        return try_manifest_from_bytes(data)

    def _stored_kinds(self, store_key: str) -> dict[str, str]:
        data = self._store.read_dataset(store_key, "vectors")
        if data is None:
            return {}
        items = try_items_from_bytes(data)
        if items is None:
            return {}
        return {item.key: item.kind for item in items}
