"""Parsing errors for source content."""

from __future__ import annotations


class ParsingError(Exception):
    """Raised when artifact content cannot be parsed."""


class UnsupportedMediaTypeError(ParsingError):
    """Raised when no parser is registered for an artifact media type."""

    def __init__(self, media_type: str) -> None:
        self.media_type = media_type
        super().__init__(f"no parser registered for media type: {media_type}")
