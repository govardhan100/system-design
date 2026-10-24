"""Unit tests for ClickHouse / OLAP analytical calculations and benchmarks."""

import pytest
from app.database import init_db
from app.clickhouse import (
    get_analytics_overview,
    get_category_distribution,
    get_customer_segment_distribution,
    get_olap_stats,
    get_regional_distribution,
    get_sales_trends,
    init_clickhouse,
    insert_sales_facts,
)
from app.benchmark import run_comparison_benchmark


@pytest.fixture(autouse=True)
def setup_olap():
    init_db()
    init_clickhouse()


def test_insert_and_analytics_aggregation():
    sample_facts = [
        {
            "order_id": 99901,
            "item_id": 1,
            "order_timestamp": "2026-10-24 12:00:00",
            "order_date": "2026-10-24",
            "customer_id": 1,
            "customer_name": "Test Customer",
            "customer_segment": "VIP",
            "customer_country": "US",
            "product_id": 10,
            "product_name": "Pro Headphones",
            "category": "Electronics",
            "quantity": 2,
            "unit_price": 200.0,
            "cost_price": 100.0,
            "discount_amount": 0.0,
            "line_total": 400.0,
            "profit": 200.0,
            "payment_method": "Credit Card",
            "order_status": "PAID",
        },
        {
            "order_id": 99902,
            "item_id": 2,
            "order_timestamp": "2026-10-24 13:00:00",
            "order_date": "2026-10-24",
            "customer_id": 2,
            "customer_name": "Second Customer",
            "customer_segment": "Regular",
            "customer_country": "DE",
            "product_id": 11,
            "product_name": "Cotton Hoodie",
            "category": "Apparel",
            "quantity": 1,
            "unit_price": 100.0,
            "cost_price": 40.0,
            "discount_amount": 10.0,
            "line_total": 90.0,
            "profit": 50.0,
            "payment_method": "PayPal",
            "order_status": "PAID",
        },
    ]

    inserted = insert_sales_facts(sample_facts)
    assert inserted >= 2

    overview = get_analytics_overview()
    assert overview["gmv"] >= 490.0
    assert overview["net_profit"] >= 250.0
    assert overview["total_orders"] >= 2
    assert overview["gross_margin_pct"] > 0

    cats = get_category_distribution()
    assert len(cats) >= 2
    cat_names = [c["category"] for c in cats]
    assert "Electronics" in cat_names
    assert "Apparel" in cat_names

    regions = get_regional_distribution()
    countries = [r["country"] for r in regions]
    assert "US" in countries or "DE" in countries

    trends = get_sales_trends()
    assert len(trends) >= 1

    segments = get_customer_segment_distribution()
    seg_names = [s["segment"] for s in segments]
    assert "VIP" in seg_names or "Regular" in seg_names


def test_comparison_benchmark():
    res = run_comparison_benchmark("category_revenue")
    assert "oltp" in res
    assert "olap" in res
    assert "comparison" in res
    assert "speedup_factor" in res["comparison"]
    assert res["oltp"]["duration_ms"] >= 0
    assert res["olap"]["duration_ms"] >= 0
