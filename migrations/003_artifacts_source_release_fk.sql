-- Migration 003: Enforce FK constraint on artifacts.source_release_id
--
-- SQLite does not support ADD CONSTRAINT on existing tables, so we recreate
-- the artifacts table with the FK constraint in place and copy all existing data.
-- The BLOB content column is preserved exactly.

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS artifacts_new (
    id                TEXT PRIMARY KEY,
    sha256            TEXT NOT NULL UNIQUE,
    media_type        TEXT NOT NULL,
    name              TEXT,
    kind              TEXT NOT NULL,
    size_bytes        INTEGER NOT NULL,
    retrieved_at      TEXT NOT NULL,
    content           BLOB NOT NULL,
    source_release_id TEXT NOT NULL REFERENCES releases(release_id) ON DELETE RESTRICT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT INTO artifacts_new
    SELECT id, sha256, media_type, name, kind, size_bytes,
           retrieved_at, content, source_release_id, created_at
    FROM artifacts;

DROP TABLE artifacts;
ALTER TABLE artifacts_new RENAME TO artifacts;

CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256);
CREATE INDEX IF NOT EXISTS idx_artifacts_source_release ON artifacts(source_release_id);

PRAGMA foreign_keys = ON;
