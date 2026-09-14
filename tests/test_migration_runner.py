from __future__ import annotations

import sqlite3

import pytest

from infrastructure.storage.migration_runner import MigrationRunner


def test_migration_runner_fresh_db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    runner = MigrationRunner(db_path)
    assert runner.get_current_version() == 0

    applied = runner.migrate()
    assert 1 in applied
    assert 2 in applied
    assert runner.get_current_version() >= 2

    # Verify tables created
    con = sqlite3.connect(db_path)
    tables = [
        r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    con.close()
    assert "schema_migrations" in tables
    assert "active_graph" in tables
    assert "artifacts" in tables
    assert "assertions" in tables
    assert "assertion_state_events" in tables
    assert "fusion_runs" in tables
    assert "release_assertions" in tables


def test_migration_runner_idempotent(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    runner = MigrationRunner(db_path)
    applied_first = runner.migrate()
    assert len(applied_first) > 0

    applied_second = runner.migrate()
    assert applied_second == []


def test_migration_runner_atomic_rollback_on_failure(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    custom_migrations = tmp_path / "custom_migrations"
    custom_migrations.mkdir()

    # Good migration 1
    (custom_migrations / "001_good.sql").write_text(
        "CREATE TABLE table_one (id INT PRIMARY KEY);", encoding="utf-8"
    )
    # Bad migration 2
    (custom_migrations / "002_bad.sql").write_text(
        "CREATE TABLE table_two (id INT PRIMARY KEY);\nINVALID SQL STATEMENT;", encoding="utf-8"
    )

    runner = MigrationRunner(db_path, migrations_dir=custom_migrations)
    with pytest.raises(sqlite3.OperationalError):
        runner.migrate()

    assert runner.get_current_version() == 1

    con = sqlite3.connect(db_path)
    tables = [
        r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    con.close()
    assert "table_one" in tables
    assert "table_two" not in tables
