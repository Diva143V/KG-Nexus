-- Migration 001: Initial Graph Schema
CREATE TABLE IF NOT EXISTS active_graph (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    nodes_json TEXT NOT NULL,
    edges_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    nodes_json TEXT NOT NULL,
    edges_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS releases (
    release_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO active_graph (id, nodes_json, edges_json)
VALUES (1, '[]', '[]');
