from __future__ import annotations

from infrastructure.storage import GraphStore


def test_graph_store_persists_active_graph_between_instances(tmp_path):
    database_path = tmp_path / "graph.sqlite3"
    first = GraphStore(database_path)
    first.replace_active([{"id": "a"}], [{"from": "a", "to": "b"}])

    second = GraphStore(database_path)
    assert second.get_active() == {
        "nodes": [{"id": "a"}],
        "edges": [{"from": "a", "to": "b"}],
    }


def test_graph_store_rolls_back_to_previous_snapshot(tmp_path):
    store = GraphStore(tmp_path / "graph.sqlite3")
    store.replace_active([{"id": "first"}], [])
    store.replace_active([{"id": "second"}], [])

    restored = store.rollback()

    assert restored == {"nodes": [{"id": "first"}], "edges": []}
    assert store.get_active() == restored


def test_graph_store_persists_release_payload(tmp_path):
    store = GraphStore(tmp_path / "graph.sqlite3")
    payload = {"fusion_run": {"result_release_id": {"value": "release-1"}}, "nodes": []}

    store.save_release("release-1", payload)

    assert store.get_release("release-1") == payload
