"""E-Commerce Website Traffic & Order Simulator.

Generates realistic customer checkout transactions with diverse product baskets,
pricing tiers, payment channels, promotional discounts, and realistic order dates.
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.database import create_order, get_customers, get_products

PAYMENT_METHODS = ["Credit Card", "PayPal", "Apple Pay", "Crypto", "Klarna"]
STATUSES = ["PAID", "PAID", "PAID", "PAID", "SHIPPED", "DELIVERED", "PENDING"]


def simulate_orders_batch(count: int = 50, historical_spread_days: int = 14) -> Dict[str, Any]:
    """Generate and commit N realistic customer orders to PostgreSQL OLTP database."""
    products = get_products()
    customers = get_customers()

    if not products or not customers:
        raise RuntimeError("Cannot simulate orders: Products or Customers catalog is empty.")

    created_orders = []
    total_gmv = 0.0

    now = datetime.now(timezone.utc)

    for i in range(count):
        cust = random.choice(customers)
        cust_id = int(cust["id"])
        country = cust.get("country", "US")

        # Select 1 to 4 distinct items for basket
        basket_size = random.choices([1, 2, 3, 4], weights=[40, 35, 18, 7])[0]
        chosen_products = random.sample(products, k=min(basket_size, len(products)))

        order_items = []
        for p in chosen_products:
            p_id = int(p["id"])
            qty = random.choices([1, 2, 3], weights=[70, 22, 8])[0]
            # Occasional discount coupon
            discount = 0.0
            if random.random() < 0.25:
                discount = round(float(p["price"]) * 0.15, 2)

            order_items.append({
                "product_id": p_id,
                "quantity": qty,
                "discount_amount": discount,
            })

        pay_method = random.choice(PAYMENT_METHODS)
        status = random.choice(STATUSES)

        res = create_order(
            customer_id=cust_id,
            items=order_items,
            payment_method=pay_method,
            shipping_country=country,
            order_status=status,
        )
        total_gmv += res["total_amount"]
        created_orders.append(res)

    return {
        "orders_generated": len(created_orders),
        "total_gmv": round(total_gmv, 2),
        "avg_order_value": round(total_gmv / len(created_orders), 2) if created_orders else 0.0,
        "sample_order_id": created_orders[0]["order_id"] if created_orders else None,
    }
