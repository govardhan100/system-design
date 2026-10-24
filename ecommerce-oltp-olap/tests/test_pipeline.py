"""Unit tests for ETL / ELT pipeline synchronization and idempotency."""

import pytest
from app.database import create_order, get_customers, get_products, init_db
from app.clickhouse import init_clickhouse
from app.pipeline import get_pipeline_telemetry, run_pipeline_sync


@pytest.fixture(autouse=True)
def setup_environment():
    init_db()
    init_clickhouse()


def test_pipeline_incremental_sync():
    customers = get_customers()
    products = get_products()

    # Create new order
    order = create_order(
        customer_id=customers[0]["id"],
        items=[
            {"product_id": products[0]["id"], "quantity": 1, "discount_amount": 5.0},
            {"product_id": products[1]["id"], "quantity": 2, "discount_amount": 0.0},
        ],
        payment_method="PayPal",
        shipping_country="DE",
        order_status="PAID",
    )

    # Telemetry should report un-synced backlog
    telemetry_before = get_pipeline_telemetry()
    assert telemetry_before["un_synced_backlog_orders"] >= 1

    # Run ETL Sync
    sync_result = run_pipeline_sync(batch_size=100)
    assert sync_result["status"] == "SUCCESS"
    assert sync_result["extracted"] >= 2
    assert sync_result["loaded"] >= 2
    assert sync_result["last_order_id"] >= order["order_id"]

    # Running sync again immediately should be NO_OP
    no_op_sync = run_pipeline_sync(batch_size=100)
    assert no_op_sync["status"] == "NO_OP"
    assert no_op_sync["extracted"] == 0

    # Backlog should now be 0
    telemetry_after = get_pipeline_telemetry()
    assert telemetry_after["un_synced_backlog_orders"] == 0
