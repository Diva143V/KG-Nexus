"""Release management: creating releases and ingesting their content."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from core.artifacts.artifact_store import ArtifactStore
from core.identifiers.identifier import Identifier
from core.parsing.parser_registry import ParserRegistry
from core.resources.parsed_record import RecordStatus
from core.resources.source_release import SourceRelease
from core.sources.errors import UnknownReleaseError, UnknownSourceError
from core.sources.source_registry import SourceRegistry
from sdk.source_adapter import SourceAdapter


class IngestionStatus(StrEnum):
    """Lifecycle state of a release ingestion."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"


class ReleaseIngestion(BaseModel):
    """Immutable outcome of a release ingestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    release_id: Identifier
    status: IngestionStatus
    artifacts: tuple[Identifier, ...] = ()
    records: tuple[Identifier, ...] = ()
    errors: tuple[str, ...] = ()
    completed_at: datetime | None = None


class SourceReleaseManager:
    """Creates releases and drives content ingestion for a source.

    Fetches release content through the configured ``SourceAdapter``,
    stores artifacts immutably via ``ArtifactStore``, and parses each
    artifact via ``ParserRegistry``. Tracks per-release ingestion status
    including partial and failed outcomes.
    """

    def __init__(
        self,
        *,
        registry: SourceRegistry,
        artifact_store: ArtifactStore,
        parser_registry: ParserRegistry,
        adapter: SourceAdapter,
    ) -> None:
        self._registry = registry
        self._artifact_store = artifact_store
        self._parsers = parser_registry
        self._adapter = adapter
        self._releases: dict[str, SourceRelease] = {}
        self._ingestions: dict[str, ReleaseIngestion] = {}

    def create_release(
        self,
        *,
        source_id: Identifier,
        version: str,
        released_at: datetime | None = None,
    ) -> SourceRelease:
        source = self._registry.get(source_id)
        if source is None:
            raise UnknownSourceError(source_id)
        release_id = Identifier(namespace="release", value=f"{source_id.value}:{version}")
        if release_id.canonical in self._releases:
            raise ValueError(f"duplicate release: {release_id.canonical}")
        release = SourceRelease(
            id=release_id,
            source_id=source_id,
            version=version,
            released_at=released_at,
        )
        self._releases[release_id.canonical] = release
        return release

    def ingest(self, release: SourceRelease) -> ReleaseIngestion:
        key = release.id.canonical
        if key not in self._releases:
            raise UnknownReleaseError(release.id)
        now = datetime.now(UTC)
        self._ingestions[key] = ReleaseIngestion(
            release_id=release.id, status=IngestionStatus.IN_PROGRESS
        )
        artifact_ids: list[Identifier] = []
        record_ids: list[Identifier] = []
        errors: list[str] = []
        seen_artifacts: set[str] = set()
        try:
            results = list(self._adapter.fetch(release))
        except Exception as exc:
            return self._finish(
                release.id,
                IngestionStatus.FAILED,
                [],
                [],
                [f"fetch failed: {exc}"],
                now,
            )
        for result in results:
            try:
                artifact = self._artifact_store.store(
                    content=result.content,
                    source_release_id=release.id,
                    media_type=result.media_type,
                    name=result.name,
                    retrieved_at=now,
                )
            except Exception as exc:
                errors.append(f"artifact {result.name}: {exc}")
                continue
            if artifact.id.canonical in seen_artifacts:
                continue
            seen_artifacts.add(artifact.id.canonical)
            artifact_ids.append(artifact.id)
            try:
                records = self._parsers.parse(
                    result.content,
                    artifact_id=artifact.id,
                    media_type=result.media_type,
                    parsed_at=now,
                )
            except Exception as exc:
                errors.append(f"parse {artifact.id.canonical}: {exc}")
                continue
            record_ids.extend(record.id for record in records)
            for record in records:
                if record.status == RecordStatus.ERROR:
                    errors.append(f"record {record.id.canonical}: {'; '.join(record.errors)}")
        if not artifact_ids and errors:
            status = IngestionStatus.FAILED
        elif errors:
            status = IngestionStatus.PARTIAL
        else:
            status = IngestionStatus.COMPLETE
        return self._finish(release.id, status, artifact_ids, record_ids, errors, now)

    def get_release(self, release_id: Identifier) -> SourceRelease | None:
        return self._releases.get(release_id.canonical)

    def ingestion_for(self, release_id: Identifier) -> ReleaseIngestion | None:
        return self._ingestions.get(release_id.canonical)

    def iter_releases(self) -> Iterable[SourceRelease]:
        return self._releases.values()

    def _finish(
        self,
        release_id: Identifier,
        status: IngestionStatus,
        artifact_ids: list[Identifier],
        record_ids: list[Identifier],
        errors: list[str],
        now: datetime,
    ) -> ReleaseIngestion:
        result = ReleaseIngestion(
            release_id=release_id,
            status=status,
            artifacts=tuple(artifact_ids),
            records=tuple(record_ids),
            errors=tuple(errors),
            completed_at=now,
        )
        self._ingestions[release_id.canonical] = result
        return result
