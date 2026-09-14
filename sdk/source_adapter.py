"""Source adapter extension contract.

Source adapters fetch concrete content for a release. Adapters are
source-specific (domain plugins); core depends only on this interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from core.resources.source_release import SourceRelease


class FetchResult(BaseModel):
    """One content blob fetched for a release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    content: bytes


@runtime_checkable
class SourceAdapter(Protocol):
    """Extension contract for fetching release content."""

    def fetch(self, release: SourceRelease) -> list[FetchResult]:
        """Return the content blobs available for ``release``."""
        ...
