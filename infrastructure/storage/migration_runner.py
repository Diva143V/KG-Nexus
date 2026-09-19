"""Migration runner for SQLite schema management."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIGRATION_FILE_PATTERN = re.compile(r"^(\d+)_(.+)\.sql$")
_MIGRATION_FILE_CACHE: dict[Path, tuple[float, str]] = {}


def _read_migration_file(path: Path) -> str:
    """Read migration file with mtime caching to avoid repeated synchronous disk reads."""
    mtime = path.stat().st_mtime
    cached = _MIGRATION_FILE_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    content = path.read_text(encoding="utf-8")
    _MIGRATION_FILE_CACHE[path] = (mtime, content)
    return content


class MigrationRunner:
    """Discovers and applies versioned SQL migrations in order."""

    def __init__(
        self,
        database_path: str | Path,
        migrations_dir: str | Path | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        if migrations_dir is not None:
            self.migrations_dir = Path(migrations_dir)
        else:
            self.migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations"

        self._mem_uri: str | None = None
        self._keepalive: sqlite3.Connection | None = None

        if str(self.database_path) != ":memory:":
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self._mem_uri = f"file:mem_{id(self)}?mode=memory&cache=shared"
            self._keepalive = sqlite3.connect(self._mem_uri, uri=True)

        self._ensure_migrations_table()

    def _connect(self) -> sqlite3.Connection:
        if self._mem_uri:
            connection = sqlite3.connect(
                self._mem_uri, uri=True, timeout=30, check_same_thread=False
            )
        else:
            connection = sqlite3.connect(self.database_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if str(self.database_path) != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _session(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_migrations_table(self) -> None:
        with self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                );
                """
            )
            connection.commit()

    def get_current_version(self) -> int:
        with self._session() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS current_version FROM schema_migrations"
            ).fetchone()
            return int(row["current_version"]) if row else 0

    def get_applied_migrations(self) -> list[dict[str, Any]]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT version, description, applied_at FROM schema_migrations ORDER BY version ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_available_migrations(self) -> list[tuple[int, str, Path]]:
        if not self.migrations_dir.exists():
            return []
        migrations: list[tuple[int, str, Path]] = []
        for path in self.migrations_dir.glob("*.sql"):
            match = MIGRATION_FILE_PATTERN.match(path.name)
            if match:
                version = int(match.group(1))
                description = match.group(2)
                migrations.append((version, description, path))
        migrations.sort(key=lambda m: m[0])
        return migrations

    def migrate(self) -> list[int]:
        """Apply all pending migrations in order inside individual transactions.

        Returns list of newly applied migration versions.
        """
        applied_versions: list[int] = []
        available = self.get_available_migrations()
        current_version = self.get_current_version()

        for version, description, path in available:
            if version <= current_version:
                continue

            sql_content = _read_migration_file(path)
            # Run the migration DDL and schema_migrations record atomically in a single script transaction.
            escaped_desc = description.replace("'", "''")
            script = (
                f"BEGIN;\n"
                f"{sql_content}\n"
                f"INSERT INTO schema_migrations (version, description) VALUES ({version}, '{escaped_desc}');\n"
                f"COMMIT;"
            )

            connection = self._connect()
            try:
                connection.executescript(script)
                applied_versions.append(version)
                current_version = version
                logger.info("Applied migration %03d_%s", version, description)
            except Exception as exc:
                try:
                    connection.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error("Failed to apply migration %03d_%s: %s", version, description, exc)
                raise
            finally:
                connection.close()

        return applied_versions
