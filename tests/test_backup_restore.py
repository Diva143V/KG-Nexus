from __future__ import annotations

from infrastructure.storage.backup import backup_database, restore_database, verify_backup
from infrastructure.storage.graph_store import GraphStore


def test_backup_and_verify(tmp_path):
    db_path = tmp_path / "live.sqlite3"
    backup_path = tmp_path / "backups" / "snapshot_01.sqlite3"

    store = GraphStore(db_path)
    store.replace_active([{"id": "node-1"}], [])

    backup_database(db_path, backup_path)
    assert backup_path.exists()
    assert verify_backup(backup_path) is True


def test_verify_backup_invalid(tmp_path):
    bad_file = tmp_path / "corrupt.sqlite3"
    bad_file.write_bytes(b"NOT A VALID SQLITE DATABASE")
    assert verify_backup(bad_file) is False


def test_restore_database(tmp_path):
    db_path = tmp_path / "live.sqlite3"
    backup_path = tmp_path / "backups" / "snapshot.sqlite3"

    store = GraphStore(db_path)
    store.replace_active([{"id": "initial"}], [])

    # Take backup with initial state
    backup_database(db_path, backup_path)

    # Make further changes in live DB
    store.replace_active([{"id": "initial"}, {"id": "added_later"}], [])
    assert len(store.get_active()["nodes"]) == 2

    # Restore from backup
    restore_database(backup_path, db_path)

    # Re-open store and check state
    restored_store = GraphStore(db_path)
    active = restored_store.get_active()
    assert len(active["nodes"]) == 1
    assert active["nodes"][0]["id"] == "initial"
