"""Benchmark and simulation comparing Modulo Hashing vs Consistent Hashing."""

import math
from typing import Any, Dict, List
from app.ring import ConsistentHashRing, md5_32


def calculate_distribution_stats(loads: List[int]) -> Dict[str, float]:
    """Calculate statistical distribution metrics for load across nodes."""
    if not loads:
        return {"min": 0, "max": 0, "avg": 0.0, "std_dev": 0.0, "cv": 0.0}

    n = len(loads)
    avg = sum(loads) / n
    variance = sum((x - avg) ** 2 for x in loads) / n
    std_dev = math.sqrt(variance)
    cv = (std_dev / avg * 100.0) if avg > 0 else 0.0

    return {
        "min": min(loads),
        "max": max(loads),
        "avg": round(avg, 2),
        "std_dev": round(std_dev, 2),
        "cv_pct": round(cv, 2),  # Coefficient of variation (%)
    }


def run_comparison_benchmark(
    num_keys: int = 10000,
    initial_nodes: int = 5,
    vnodes_count: int = 150,
) -> Dict[str, Any]:
    """
    Run comprehensive simulation of Modulo Hashing vs Consistent Hashing (No Vnodes vs Vnodes).
    Measures key distribution uniformity and churn rate during node addition/removal.
    """
    num_keys = max(100, min(num_keys, 50000))
    initial_nodes = max(3, min(initial_nodes, 20))

    node_ids = [f"node_{i}" for i in range(initial_nodes)]
    keys = [f"cache_key_user_{i}_{i * 37}" for i in range(num_keys)]

    # -------------------------------------------------------------
    # 1. Modulo Hashing (Initial)
    # -------------------------------------------------------------
    modulo_assignments_n: Dict[str, str] = {}
    modulo_loads_n: Dict[str, int] = {nid: 0 for nid in node_ids}
    for k in keys:
        h = md5_32(k)
        target = node_ids[h % initial_nodes]
        modulo_assignments_n[k] = target
        modulo_loads_n[target] += 1

    # -------------------------------------------------------------
    # 2. Consistent Hashing (No Virtual Nodes: vnodes = 1)
    # -------------------------------------------------------------
    ring_basic = ConsistentHashRing(default_vnodes=1)
    for nid in node_ids:
        ring_basic.add_node(nid, vnodes=1, rebalance=False)

    basic_assignments_n: Dict[str, str] = {}
    basic_loads_n: Dict[str, int] = {nid: 0 for nid in node_ids}
    for k in keys:
        target = ring_basic.get_node(k).node_id
        basic_assignments_n[k] = target
        basic_loads_n[target] += 1

    # -------------------------------------------------------------
    # 3. Consistent Hashing (With Virtual Nodes: vnodes = vnodes_count)
    # -------------------------------------------------------------
    ring_vnode = ConsistentHashRing(default_vnodes=vnodes_count)
    for nid in node_ids:
        ring_vnode.add_node(nid, vnodes=vnodes_count, rebalance=False)

    vnode_assignments_n: Dict[str, str] = {}
    vnode_loads_n: Dict[str, int] = {nid: 0 for nid in node_ids}
    for k in keys:
        target = ring_vnode.get_node(k).node_id
        vnode_assignments_n[k] = target
        vnode_loads_n[target] += 1

    # -------------------------------------------------------------
    # SIMULATION: Add Node (N -> N + 1)
    # -------------------------------------------------------------
    new_node = f"node_{initial_nodes}"
    nodes_plus_one = node_ids + [new_node]

    # Modulo after add
    modulo_churn_add = 0
    for k in keys:
        h = md5_32(k)
        target = nodes_plus_one[h % len(nodes_plus_one)]
        if target != modulo_assignments_n[k]:
            modulo_churn_add += 1

    # Basic Ring after add
    ring_basic.add_node(new_node, vnodes=1, rebalance=False)
    basic_churn_add = 0
    for k in keys:
        target = ring_basic.get_node(k).node_id
        if target != basic_assignments_n[k]:
            basic_churn_add += 1

    # VNode Ring after add
    ring_vnode.add_node(new_node, vnodes=vnodes_count, rebalance=False)
    vnode_churn_add = 0
    for k in keys:
        target = ring_vnode.get_node(k).node_id
        if target != vnode_assignments_n[k]:
            vnode_churn_add += 1

    # -------------------------------------------------------------
    # SIMULATION: Remove Node (N -> N - 1)
    # -------------------------------------------------------------
    nodes_minus_one = node_ids[:-1]
    removed_node = node_ids[-1]

    # Modulo after remove
    modulo_churn_rem = 0
    for k in keys:
        h = md5_32(k)
        target = nodes_minus_one[h % len(nodes_minus_one)]
        if target != modulo_assignments_n[k]:
            modulo_churn_rem += 1

    # Ring basic after remove
    ring_basic_rem = ConsistentHashRing(default_vnodes=1)
    for nid in nodes_minus_one:
        ring_basic_rem.add_node(nid, vnodes=1, rebalance=False)
    basic_churn_rem = 0
    for k in keys:
        target = ring_basic_rem.get_node(k).node_id
        if target != basic_assignments_n[k]:
            basic_churn_rem += 1

    # Ring vnode after remove
    ring_vnode_rem = ConsistentHashRing(default_vnodes=vnodes_count)
    for nid in nodes_minus_one:
        ring_vnode_rem.add_node(nid, vnodes=vnodes_count, rebalance=False)
    vnode_churn_rem = 0
    for k in keys:
        target = ring_vnode_rem.get_node(k).node_id
        if target != vnode_assignments_n[k]:
            vnode_churn_rem += 1

    return {
        "metadata": {
            "total_keys": num_keys,
            "initial_nodes": initial_nodes,
            "vnodes_per_node": vnodes_count,
        },
        "modulo": {
            "name": "Modulo Hashing (hash % N)",
            "stats": calculate_distribution_stats(list(modulo_loads_n.values())),
            "loads": modulo_loads_n,
            "churn_add_node": {
                "keys_moved": modulo_churn_add,
                "percentage": round((modulo_churn_add / num_keys) * 100.0, 2),
                "theoretical_percentage": round((initial_nodes / (initial_nodes + 1)) * 100.0, 2),
            },
            "churn_remove_node": {
                "keys_moved": modulo_churn_rem,
                "percentage": round((modulo_churn_rem / num_keys) * 100.0, 2),
                "theoretical_percentage": round(((initial_nodes - 1) / initial_nodes) * 100.0, 2),
            },
        },
        "consistent_basic": {
            "name": "Consistent Hashing (1 VNode)",
            "stats": calculate_distribution_stats(list(basic_loads_n.values())),
            "loads": basic_loads_n,
            "churn_add_node": {
                "keys_moved": basic_churn_add,
                "percentage": round((basic_churn_add / num_keys) * 100.0, 2),
                "theoretical_percentage": round((1.0 / (initial_nodes + 1)) * 100.0, 2),
            },
            "churn_remove_node": {
                "keys_moved": basic_churn_rem,
                "percentage": round((basic_churn_rem / num_keys) * 100.0, 2),
                "theoretical_percentage": round((1.0 / initial_nodes) * 100.0, 2),
            },
        },
        "consistent_vnodes": {
            "name": f"Consistent Hashing ({vnodes_count} VNodes)",
            "stats": calculate_distribution_stats(list(vnode_loads_n.values())),
            "loads": vnode_loads_n,
            "churn_add_node": {
                "keys_moved": vnode_churn_add,
                "percentage": round((vnode_churn_add / num_keys) * 100.0, 2),
                "theoretical_percentage": round((1.0 / (initial_nodes + 1)) * 100.0, 2),
            },
            "churn_remove_node": {
                "keys_moved": vnode_churn_rem,
                "percentage": round((vnode_churn_rem / num_keys) * 100.0, 2),
                "theoretical_percentage": round((1.0 / initial_nodes) * 100.0, 2),
            },
        },
    }
