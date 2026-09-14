"""Domain-neutral built-in normalizers.

These normalizers never decide biomedical identity: they do not merge
entities, infer relationships, or assign domain meaning.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

_IDENTIFIER_ALLOWED = re.compile(r"[^A-Za-z0-9_.:-]")


class WhitespaceNormalizer:
    """Collapses runs of whitespace to a single space and trims edges.

    Handles all Unicode whitespace, including non-breaking spaces.
    """

    name = "whitespace"
    version = "1.0.0"

    def normalize(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()


class UnicodeNormalizer:
    """Canonicalizes Unicode to NFC form."""

    name = "unicode"
    version = "1.0.0"

    def normalize(self, value: str) -> str:
        return unicodedata.normalize("NFC", value)


class CaseMode(StrEnum):
    """Configured case transformation modes."""

    LOWER = "lower"
    UPPER = "upper"
    TITLE = "title"


class CaseNormalizer:
    """Applies case normalization only when explicitly configured."""

    version = "1.0.0"

    def __init__(self, mode: CaseMode = CaseMode.LOWER) -> None:
        self._mode = mode

    @property
    def name(self) -> str:
        return f"case:{self._mode.value}"

    @property
    def mode(self) -> CaseMode:
        return self._mode

    def normalize(self, value: str) -> str:
        if self._mode is CaseMode.LOWER:
            return value.lower()
        if self._mode is CaseMode.UPPER:
            return value.upper()
        return value.title()


class IdentifierNormalizer:
    """Formats a value into an identifier-like form.

    Collapses whitespace to underscores, drops characters not commonly
    allowed in identifiers, and trims stray separators. Case is preserved.
    """

    name = "identifier"
    version = "1.0.0"

    def normalize(self, value: str) -> str:
        value = value.strip()
        value = re.sub(r"\s+", "_", value)
        value = _IDENTIFIER_ALLOWED.sub("_", value)
        value = re.sub(r"_+", "_", value)
        return value.strip("_")


class LiteralNormalizer:
    """Canonicalizes literal forms.

    Trims outer quotes and collapses interior whitespace to single spaces.
    """

    name = "literal"
    version = "1.0.0"

    def normalize(self, value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1].strip()
        return re.sub(r"\s+", " ", value)
