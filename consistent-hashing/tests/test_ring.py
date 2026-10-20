"""Unit tests for ConsistentHashRing core logic."""

import pytest
from app.ring import ConsistentHashRing, RING_SIZE, fnv1a_32, md5_32


def test_hash_functions_deterministic():
    """Hash functions should produce identical 32-bit unsigned output for identical keys."""
    val = "user_account_10948"
    assert fnv1a_32(val) == fnv1a_32(val)
    assert 0 <= fnv1a_32(val) < RING_SIZE
    assert md5_32(val) == md5_32(val)
    assert 0 <= md5_32(val) < RING_SIZE


def test_ring_add_and_remove_nodes():
    """Verify nodes and virtual nodes are placed and removed correctly."""
    ring = ConsistentHashRing(default_vnodes=50)
    assert ring.total_nodes == 0
    assert ring.total_vnodes == 0

    ring.add_node("node-1", vnodes=40)
    assert ring.total_nodes == 1
    assert ring.total_vnodes == 40
    assert len(ring._sorted_tokens) == 40

    ring.add_node("node-2", vnodes=60)
    assert ring.total_nodes == 2
    assert ring.total_vnodes == 100

    # Tokens must be sorted ascending
    assert ring._sorted_tokens == sorted(ring._sorted_tokens)

    # Remove node-1
    report = ring.remove_node("node-1")
    assert ring.total_nodes == 1
    assert ring.total_vnodes == 60
    assert report["node_id"] == "node-1"


def test_ring_single_node_gets_all_keys():
    """When only 1 node is on the ring, all keys must map to it."""
    ring = ConsistentHashRing(default_vnodes=20)
    ring.add_node("solo-node")

    for k in ["alpha", "beta", "gamma", "delta", "epsilon", "12345"]:
        node = ring.get_node(k)
        assert node is not None
        assert node.node_id == "solo-node"


def test_ring_replication_distinct_physical_nodes():
    """Replication must return distinct physical nodes even with hundreds of virtual nodes."""
    ring = ConsistentHashRing(default_vnodes=100, replication_factor=3)
    ring.add_node("node-a")
    ring.add_node("node-b")
    ring.add_node("node-c")
    ring.add_node("node-d")

    for k in ["test_key_1", "test_key_2", "order_9981"]:
        nodes = ring.get_nodes(k, count=3)
        assert len(nodes) == 3
        # Ensure all node IDs in replica set are strictly distinct
        node_ids = [n.node_id for n in nodes]
        assert len(set(node_ids)) == 3


def test_partition_ownership_sum_100_percent():
    """Sum of all partition arc lengths on the ring must total 100%."""
    ring = ConsistentHashRing(default_vnodes=120)
    ring.add_node("node-1")
    ring.add_node("node-2")
    ring.add_node("node-3")

    partitions = ring.get_partition_ownership()
    total_pct = sum(p["ring_percentage"] for p in partitions)
    # Floating point rounding allows slight epsilon
    assert 99.9 <= total_pct <= 100.1
