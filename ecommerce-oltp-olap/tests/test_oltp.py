"""Unit tests for PostgreSQL OLTP layer."""

import pytest
from app.database import (
    create_order,
    get_customers,
    get_oltp_stats,
    get_products,
    get_recent_orders,
    init_db,
)


@pytest.fixture(autouse=True)
def setup_database():
    init_db()


def test_get_products_and_customers():
    products = get_products()
    customers = get_customers()

    assert len(products) > 0, "Product catalog should contain seeded items"
    assert len(customers) > 0, "Customers catalog should contain seeded users"

    first_product = products[0]
    assert "price" in first_product
    assert "category" in first_product
    assert first_product["price"] > 0


def test_create_order_acid_transaction():
    customers = get_customers()
    products = get_products()
    cust_id = customers[0]["id"]
    prod = products[0]

    initial_stock = prod["stock_quantity"]

    order = create_order(
        customer_id=cust_id,
        items=[{"product_id": prod["id"], "quantity": 2, "discount_amount": 0.0}],
        payment_method="Credit Card",
        shipping_country="US",
        order_status="PAID",
    )

    assert order["order_id"] > 0
    assert order["customer_id"] == cust_id
    assert order["items_count"] == 1
    expected_total = round(float(prod["price"]) * 2, 2)
    assert abs(order["total_amount"] - expected_total) < 0.01

    # Verify inventory was decremented
    updated_products = get_products()
    updated_prod = next(p for p in updated_products if p["id"] == prod["id"])
    assert updated_prod["stock_quantity"] == initial_stock - 2


def test_recent_orders_inspector():
    recent = get_recent_orders(limit=5)
    assert isinstance(recent, list)
    if recent:
        assert "order_id" in recent[0]
        assert "customer_name" in recent[0]
        assert "total_amount" in recent[0]


def test_oltp_stats():
    stats = get_oltp_stats()
    assert "engine" in stats
    assert stats["total_products"] > 0
    assert stats["total_customers"] > 0
