from __future__ import annotations

from core.normalization.normalizers import (
    CaseMode,
    CaseNormalizer,
    IdentifierNormalizer,
    LiteralNormalizer,
    UnicodeNormalizer,
    WhitespaceNormalizer,
)


def test_whitespace_collapses_and_trims() -> None:
    normalizer = WhitespaceNormalizer()
    assert normalizer.normalize("  a   b  ") == "a b"


def test_whitespace_handles_tabs_and_newlines() -> None:
    normalizer = WhitespaceNormalizer()
    assert normalizer.normalize("a\tb\nc") == "a b c"


def test_whitespace_handles_nbsp() -> None:
    normalizer = WhitespaceNormalizer()
    assert normalizer.normalize("a\u00a0b") == "a b"


def test_whitespace_is_idempotent() -> None:
    normalizer = WhitespaceNormalizer()
    once = normalizer.normalize(" a   b ")
    assert normalizer.normalize(once) == once


def test_unicode_normalizes_to_nfc() -> None:
    normalizer = UnicodeNormalizer()
    assert normalizer.normalize("e\u0301") == "\u00e9"


def test_unicode_is_idempotent() -> None:
    normalizer = UnicodeNormalizer()
    once = normalizer.normalize("e\u0301")
    assert normalizer.normalize(once) == once


def test_case_lower() -> None:
    normalizer = CaseNormalizer(CaseMode.LOWER)
    assert normalizer.normalize("HELLO World") == "hello world"


def test_case_upper() -> None:
    normalizer = CaseNormalizer(CaseMode.UPPER)
    assert normalizer.normalize("hello") == "HELLO"


def test_case_title() -> None:
    normalizer = CaseNormalizer(CaseMode.TITLE)
    assert normalizer.normalize("hello world") == "Hello World"


def test_case_default_is_lower() -> None:
    normalizer = CaseNormalizer()
    assert normalizer.normalize("HELLO") == "hello"


def test_case_name_includes_mode() -> None:
    assert CaseNormalizer(CaseMode.LOWER).name == "case:lower"
    assert CaseNormalizer(CaseMode.UPPER).name == "case:upper"
    assert CaseNormalizer(CaseMode.TITLE).name == "case:title"


def test_identifier_formats_spaces() -> None:
    normalizer = IdentifierNormalizer()
    assert normalizer.normalize("Some Value") == "Some_Value"


def test_identifier_strips_disallowed_characters() -> None:
    normalizer = IdentifierNormalizer()
    assert normalizer.normalize("a b$%c!!") == "a_b_c"


def test_identifier_collapses_underscores() -> None:
    normalizer = IdentifierNormalizer()
    assert normalizer.normalize("a   b") == "a_b"


def test_identifier_trims_separators() -> None:
    normalizer = IdentifierNormalizer()
    assert normalizer.normalize("  _x_  ") == "x"


def test_literal_trims_quotes() -> None:
    normalizer = LiteralNormalizer()
    assert normalizer.normalize('"hello"') == "hello"
    assert normalizer.normalize("'hello'") == "hello"


def test_literal_collapses_whitespace() -> None:
    normalizer = LiteralNormalizer()
    assert normalizer.normalize("a   b") == "a b"


def test_literal_empty_quotes() -> None:
    normalizer = LiteralNormalizer()
    assert normalizer.normalize('""') == ""
