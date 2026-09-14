"""Architectural import guards.

These tests fail if Core imports domain-specific, plugin, Neo4j, or
LLM-specific code. Core may only depend on its own modules, the SDK,
contracts, the standard library, and explicitly allowed domain-neutral
third-party libraries.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent / "core"

STDLIB = frozenset(sys.stdlib_module_names)

ALLOWED_THIRD_PARTY = frozenset({"pydantic", "pydantic_settings", "rdflib"})

ALLOWED_IMPORT_ROOTS = frozenset({"core", "sdk", "contracts"}) | ALLOWED_THIRD_PARTY

FORBIDDEN_IMPORT_ROOTS = {
    "plugins": "Core must not import plugin implementations",
    "biomedical": "Core must not import biomedical code",
    "bio": "Core must not import biomedical code",
    "neo4j": "Core must not import Neo4j",
    "openai": "Core must not import a specific LLM implementation",
    "anthropic": "Core must not import a specific LLM implementation",
    "langchain": "Core must not import a specific LLM implementation",
    "transformers": "Core must not import a specific LLM implementation",
    "llama_index": "Core must not import a specific LLM implementation",
}

FORBIDDEN_PROJECTION_TOKENS = (
    "neo4j",
    "cypher",
    "elasticsearch",
    "opensearch",
    "qdrant",
    "chromadb",
    "parquet",
)


def iter_python_files() -> list[Path]:
    return sorted(CORE_DIR.rglob("*.py"))


def test_core_has_no_forbidden_imports() -> None:
    violations: list[str] = []
    for file in iter_python_files():
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    reason = FORBIDDEN_IMPORT_ROOTS.get(root)
                    if reason is not None:
                        violations.append(f"{file}: imports {alias.name} ({reason})")
            elif isinstance(node, ast.ImportFrom):
                module = node.module
                if module is None:
                    continue
                root = module.split(".", 1)[0]
                reason = FORBIDDEN_IMPORT_ROOTS.get(root)
                if reason is not None:
                    violations.append(f"{file}: imports {module} ({reason})")
    assert not violations, "\n".join(violations)


def test_core_imports_only_stdlib_interfaces_or_contracts() -> None:
    violations: list[str] = []
    for file in iter_python_files():
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root not in ALLOWED_IMPORT_ROOTS and root not in STDLIB:
                        violations.append(
                            f"{file}: imports {alias.name} "
                            f"(not in stdlib or {sorted(ALLOWED_IMPORT_ROOTS)})"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module
                if module is None:
                    continue
                root = module.split(".", 1)[0]
                if root not in ALLOWED_IMPORT_ROOTS and root not in STDLIB:
                    violations.append(
                        f"{file}: imports {module} "
                        f"(not in stdlib or {sorted(ALLOWED_IMPORT_ROOTS)})"
                    )
    assert not violations, "\n".join(violations)


def test_core_projection_has_no_backend_specific_tokens() -> None:
    projection_dir = CORE_DIR / "projection"
    violations: list[str] = []
    for file in sorted(projection_dir.rglob("*.py")):
        lowered = file.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_PROJECTION_TOKENS:
            if token in lowered:
                violations.append(f"{file}: contains forbidden token {token!r}")
    assert not violations, "\n".join(violations)
