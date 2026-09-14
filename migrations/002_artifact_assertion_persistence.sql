-- Migration 002: Artifact and Assertion Persistence

CREATE TABLE IF NOT EXISTS artifacts (
    id               TEXT PRIMARY KEY,
    sha256           TEXT NOT NULL UNIQUE,
    media_type       TEXT NOT NULL,
    name             TEXT,
    kind             TEXT NOT NULL,
    size_bytes       INTEGER NOT NULL,
    retrieved_at     TEXT NOT NULL,
    content          BLOB NOT NULL,
    source_release_id TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON artifacts(sha256);

CREATE TABLE IF NOT EXISTS assertions (
    id                   TEXT PRIMARY KEY,
    subject_id           TEXT NOT NULL,
    predicate            TEXT NOT NULL,
    object_id            TEXT NOT NULL,
    status_at_creation   TEXT NOT NULL,
    confidence_value     REAL,
    confidence_method    TEXT,
    evidence_json        TEXT NOT NULL DEFAULT '[]',
    provenance_json      TEXT NOT NULL,
    context_json         TEXT,
    source_artifact_id   TEXT GENERATED ALWAYS AS
                           (json_extract(provenance_json, '$.source_artifact_id')) STORED,
    graph_origin_id      TEXT GENERATED ALWAYS AS
                           (json_extract(provenance_json, '$.graph_origin_id')) STORED,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_assertions_source_artifact ON assertions(source_artifact_id);
CREATE INDEX IF NOT EXISTS idx_assertions_graph_origin    ON assertions(graph_origin_id);
CREATE INDEX IF NOT EXISTS idx_assertions_predicate       ON assertions(predicate);

CREATE TABLE IF NOT EXISTS assertion_state_events (
    event_id        TEXT PRIMARY KEY,
    assertion_id    TEXT NOT NULL REFERENCES assertions(id),
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    activity_id     TEXT NOT NULL,
    policy_version  TEXT NOT NULL,
    reason_code     TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_state_events_assertion ON assertion_state_events(assertion_id);

CREATE TABLE IF NOT EXISTS fusion_runs (
    release_id      TEXT PRIMARY KEY REFERENCES releases(release_id),
    config_json     TEXT NOT NULL,
    config_digest   TEXT NOT NULL,
    policy_digest   TEXT NOT NULL,
    engine_version  TEXT NOT NULL,
    input_artifact_ids TEXT NOT NULL DEFAULT '[]',
    output_digest   TEXT NOT NULL,
    conflicts_json  TEXT NOT NULL DEFAULT '[]',
    audit_json      TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS release_assertions (
    release_id    TEXT NOT NULL REFERENCES releases(release_id),
    assertion_id  TEXT NOT NULL REFERENCES assertions(id),
    PRIMARY KEY (release_id, assertion_id)
);
