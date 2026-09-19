"""Database hot backup, verification, and restore utilities."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def backup_database(db_path: Path | str, backup_path: Path | str) -> None:
    """Hot backup using sqlite3.Connection.backup(). Safe while database is in use."""
    src = Path(db_path)
    dst = Path(backup_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    src_con = sqlite3.connect(src)
    try:
        try:
            src_con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as exc:
            logger.warning("WAL checkpoint failed before backup of %s: %s", src, exc)
        dst_con = sqlite3.connect(dst)
        try:
            src_con.backup(dst_con)
        finally:
            dst_con.close()
    finally:
        src_con.close()


def verify_backup(backup_path: Path | str) -> bool:
    """Open backup in read-only mode, run PRAGMA integrity_check, return True if clean.

    integrity_check returns one row per error plus a final 'ok' row when clean.
    All rows must equal 'ok' for the backup to be considered valid.
    """
    dst = Path(backup_path)
    if not dst.exists() or dst.stat().st_size == 0:
        return False

    uri_path = dst.resolve().as_uri()
    con = sqlite3.connect(f"{uri_path}?mode=ro", uri=True)
    try:
        cur = con.execute("PRAGMA integrity_check")
        rows = cur.fetchall()
        return bool(rows) and all(row[0] == "ok" for row in rows)
    except Exception as exc:
        logger.error("Backup verification failed for %s: %s", dst, exc, exc_info=True)
        return False
    finally:
        con.close()


def restore_database(backup_path: Path | str, db_path: Path | str) -> None:
    """Restore by streaming backup over destination database using SQLite backup API.

    Safe across platforms (including Windows WAL locking) and ensures
    transaction-level consistency.
    """
    src = Path(backup_path)
    dst = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"Backup file not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    src_con = sqlite3.connect(src)
    try:
        dst_con = sqlite3.connect(dst)
        try:
            src_con.backup(dst_con)
            try:
                dst_con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
        finally:
            dst_con.close()
    finally:
        src_con.close()
