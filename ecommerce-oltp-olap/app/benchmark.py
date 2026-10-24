"""OLTP vs OLAP Side-by-Side Performance Benchmark Suite.

Executes identical business intelligence queries concurrently on:
1. PostgreSQL (Row-Store OLTP with Relational JOINs)
2. ClickHouse (Column-Store OLAP with Vectorized Execution)
Measures latency, calculates speedup multipliers, and contrasts I/O dynamics.
"""

from typing import Any, Dict

from app.database import run_oltp_benchmark_query
from app.clickhouse import run_olap_benchmark_query

BENCHMARK_DESCRIPTIONS = {
    "category_revenue": {
        "title": "Category Revenue & Gross Margin Analysis",
        "description": "Aggregates revenue, unit volume, total profit, and average price across all merchandise categories.",
        "oltp_query": "SELECT p.category, SUM(oi.quantity), SUM(oi.line_total), SUM(profit) FROM orders JOIN order_items JOIN products GROUP BY p.category",
        "olap_query": "SELECT category, sum(quantity), sum(line_total), sum(profit) FROM sales_fact GROUP BY category",
    },
    "segment_metrics": {
        "title": "Customer Loyalty Segment & Geographic Breakdown",
        "description": "Multi-dimensional grouping by customer loyalty tiers (VIP, Regular, New) and international shipping countries.",
        "oltp_query": "SELECT c.segment, c.country, COUNT(DISTINCT o.id), SUM(o.total_amount) FROM orders JOIN customers GROUP BY c.segment, c.country",
        "olap_query": "SELECT customer_segment, customer_country, countDistinct(order_id), sum(line_total) FROM sales_fact GROUP BY customer_segment, customer_country",
    },
    "monthly_trend": {
        "title": "Historical Monthly Revenue Trajectory",
        "description": "Chronological timeline grouping orders by month to evaluate growth velocity and seasonal trends.",
        "oltp_query": "SELECT TO_CHAR(created_at, 'YYYY-MM'), COUNT(DISTINCT id), SUM(total_amount) FROM orders GROUP BY TO_CHAR(created_at, 'YYYY-MM')",
        "olap_query": "SELECT toYYYYMM(order_date), countDistinct(order_id), sum(line_total) FROM sales_fact GROUP BY toYYYYMM(order_date)",
    },
    "discount_filter": {
        "title": "Promotional Discount & High-Volume Filter",
        "description": "Point-filtered query filtering for PAID orders where promotional discounts were applied, grouped by top products.",
        "oltp_query": "SELECT p.name, SUM(oi.quantity), SUM(oi.line_total) FROM order_items JOIN orders JOIN products WHERE status='PAID' AND discount > 0 GROUP BY p.name",
        "olap_query": "SELECT product_name, sum(quantity), sum(line_total) FROM sales_fact WHERE order_status='PAID' AND discount_amount > 0 GROUP BY product_name",
    },
}


def run_comparison_benchmark(query_type: str = "category_revenue") -> Dict[str, Any]:
    """Execute both engines and synthesize comparative metrics."""
    if query_type not in BENCHMARK_DESCRIPTIONS:
        query_type = "category_revenue"

    meta = BENCHMARK_DESCRIPTIONS[query_type]

    # Execute on OLTP
    oltp_res = run_oltp_benchmark_query(query_type)

    # Execute on OLAP
    olap_res = run_olap_benchmark_query(query_type)

    oltp_ms = max(0.01, oltp_res["duration_ms"])
    olap_ms = max(0.01, olap_res["duration_ms"])

    speedup = round(oltp_ms / olap_ms, 1)

    return {
        "query_type": query_type,
        "title": meta["title"],
        "description": meta["description"],
        "queries": {
            "oltp": meta["oltp_query"],
            "olap": meta["olap_query"],
        },
        "oltp": oltp_res,
        "olap": olap_res,
        "comparison": {
            "speedup_factor": f"{speedup}x",
            "faster_engine": "ClickHouse OLAP" if olap_ms <= oltp_ms else "PostgreSQL OLTP",
            "latency_reduction_pct": f"{round(max(0, (oltp_ms - olap_ms) / oltp_ms * 100), 1)}%",
            "architectural_verdict": (
                "ClickHouse reads only the requested columnar files from disk/RAM with zero row pointer traversal. "
                "In contrast, PostgreSQL must load entire 8KB row pages containing unqueried fields, reconstruct rows, "
                "and execute expensive hash/nested-loop joins in CPU memory."
            ),
        },
    }
