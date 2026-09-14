-- Migration 005: Create release_lifecycle and release_status_history tables
--
-- Stores lifecycle and status change records in versioned tables
-- to preserve immutability of the releases.payload_json column.

CREATE TABLE IF NOT EXISTS release_lifecycle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id TEXT NOT NULL,
    lifecycle_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (release_id) REFERENCES releases(release_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_release_lifecycle_release ON release_lifecycle(release_id);

CREATE TABLE IF NOT EXISTS release_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id TEXT NOT NULL,
    status TEXT NOT NULL,
    quarantine_reasons TEXT,
    changed_at TEXT NOT NULL,
    FOREIGN KEY (release_id) REFERENCES releases(release_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_release_status_history_release ON release_status_history(release_id);
CREATE INDEX IF NOT EXISTS idx_release_status_history_status ON release_status_history(status);