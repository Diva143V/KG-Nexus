"""Canonicalizable literal values for attribute assertions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class LiteralType(StrEnum):
    """Domain-neutral categories of literal values."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"


class LiteralValue(BaseModel):
    """A typed literal value with a deterministic canonical form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: LiteralType
    value: str | int | float | bool | datetime

    @model_validator(mode="after")
    def _value_matches_type(self) -> Self:
        if self.type is LiteralType.STRING and not isinstance(self.value, str):
            raise ValueError("string literal requires a str value")
        if self.type is LiteralType.INTEGER and not isinstance(self.value, int):
            raise ValueError("integer literal requires an int value")
        if self.type is LiteralType.FLOAT and not isinstance(self.value, float):
            raise ValueError("float literal requires a float value")
        if self.type is LiteralType.BOOLEAN and not isinstance(self.value, bool):
            raise ValueError("boolean literal requires a bool value")
        if self.type is LiteralType.DATETIME and not isinstance(self.value, datetime):
            raise ValueError("datetime literal requires a datetime value")
        return self


def canonical_literal(literal: LiteralValue) -> str:
    """Return the deterministic canonical string form of a literal.

    Datetimes are normalized to UTC ISO-8601; floats use Python's
    shortest round-trip representation. The canonical form depends only
    on the logical value, not on how it was written.
    """
    if literal.type is LiteralType.DATETIME:
        value = literal.value
        if not isinstance(value, datetime):
            raise ValueError("datetime literal requires a datetime value")
        if value.tzinfo is None:
            raise ValueError("datetime literal must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if literal.type is LiteralType.FLOAT:
        value = literal.value
        if not isinstance(value, float):
            raise ValueError("float literal requires a float value")
        return repr(value)
    if literal.type is LiteralType.INTEGER:
        value = literal.value
        if not isinstance(value, int):
            raise ValueError("integer literal requires an int value")
        return str(value)
    if literal.type is LiteralType.BOOLEAN:
        value = literal.value
        if not isinstance(value, bool):
            raise ValueError("boolean literal requires a bool value")
        return "true" if value else "false"
    value = literal.value
    if not isinstance(value, str):
        raise ValueError("string literal requires a str value")
    return value
