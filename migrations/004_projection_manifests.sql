-- Migration 004: Create projection_manifests table
--
-- Persists projection manifests, digests, record counts, and status transitions
-- with a foreign key to the releases table for transactional durability.

CREATE TABLE IF NOT EXISTS projection_manifests (
    projection_id   TEXT PRIMARY KEY,
    release_id      TEXT NOT NULL REFERENCES releases(release_id) ON DELETE CASCADE,
    backend_id      TEXT NOT NULL,
    status          TEXT NOT NULL,
    schema_version  TEXT NOT NULL DEFAULT '1.0.0',
    model_version   TEXT,
    input_digest    TEXT NOT NULL,
    output_digest   TEXT NOT NULL,
    record_count    INTEGER NOT NULL DEFAULT 0,
    manifest_json   TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    activated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_projection_release ON projection_manifests(release_id);
CREATE INDEX IF NOT EXISTS idx_projection_backend ON projection_manifests(backend_id);
CREATE INDEX IF NOT EXISTS idx_projection_status ON projection_manifests(status);
