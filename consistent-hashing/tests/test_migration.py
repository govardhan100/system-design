"""Tests verifying theoretical key migration churn rates."""

import pytest
from app.benchmark import run_comparison_benchmark
from app.ring import ConsistentHashRing


def test_consistent_hashing_vs_modulo_churn():
    """
    Empirically verifies that Consistent Hashing with virtual nodes has significantly
    lower churn than Modulo hashing during node additions and removals.
    """
    total_keys = 5000
    initial_nodes = 4  # N = 4, adding 1 -> N = 5
    result = run_comparison_benchmark(
        num_keys=total_keys,
        initial_nodes=initial_nodes,
        vnodes_count=150,
    )

    modulo_add_churn = result["modulo"]["churn_add_node"]["percentage"]
    consistent_add_churn = result["consistent_vnodes"]["churn_add_node"]["percentage"]

    # When N=4 -> 5:
    # Modulo churn is ~ 80% (4 / 5)
    # Consistent Hashing churn is ~ 20% (1 / 5)
    assert modulo_add_churn > 70.0
    assert 10.0 <= consistent_add_churn <= 35.0

    # Consistent hashing should move substantially fewer keys (at least 2x better)
    assert modulo_add_churn > 2.0 * consistent_add_churn


def test_virtual_nodes_improve_load_balance():
    """
    Empirically verifies that virtual nodes lower the coefficient of variation (CV)
    compared to 1-vnode consistent hashing.
    """
    result = run_comparison_benchmark(
        num_keys=10000,
        initial_nodes=5,
        vnodes_count=150,
    )

    basic_cv = result["consistent_basic"]["stats"]["cv_pct"]
    vnodes_cv = result["consistent_vnodes"]["stats"]["cv_pct"]

    # Virtual nodes provide much more uniform distribution (lower CV)
    assert vnodes_cv < basic_cv
