"""Integration tests for FastAPI endpoints in consistent-hashing module."""

import pytest
from fastapi.testclient import TestClient
from app.main import app, seed_default_nodes

client = TestClient(app)


def setup_function():
    """Reset ring before each test."""
    client.post("/api/ring/reset")


def test_healthz_and_readyz():
    resp_h = client.get("/healthz")
    assert resp_h.status_code == 200
    assert resp_h.json()["status"] == "ok"

    resp_r = client.get("/readyz")
    assert resp_r.status_code == 200
    assert resp_r.json()["status"] == "ready"


def test_get_ring_state():
    resp = client.get("/api/ring/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_nodes"] == 4
    assert len(data["nodes"]) == 4
    assert len(data["partitions"]) == 4


def test_insert_and_lookup_key():
    # Insert key
    put_resp = client.post("/api/ring/keys", json={"key": "session_user_890", "value": "active"})
    assert put_resp.status_code == 200
    put_data = put_resp.json()
    assert put_data["status"] == "stored"
    assert "routing" in put_data
    primary = put_data["routing"]["primary_node"]
    assert primary is not None

    # Lookup key
    get_resp = client.get("/api/ring/keys/session_user_890")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["found"] is True
    assert get_data["value"] == "active"


def test_add_and_remove_node_api():
    # Add new node
    add_resp = client.post(
        "/api/ring/nodes",
        json={"node_id": "node-omega", "label": "Omega Node", "vnodes": 50, "color": "#8b5cf6"},
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["state"]["total_nodes"] == 5

    # Remove node
    del_resp = client.delete("/api/ring/nodes/node-omega")
    assert del_resp.status_code == 200
    assert del_resp.json()["state"]["total_nodes"] == 4


def test_benchmark_api():
    resp = client.post(
        "/api/benchmark",
        json={"num_keys": 500, "initial_nodes": 4, "vnodes_count": 50},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "modulo" in data
    assert "consistent_basic" in data
    assert "consistent_vnodes" in data
