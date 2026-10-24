"""Unit tests for FastAPI endpoints."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz():
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_cluster_status():
    resp = client.get("/api/cluster/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "oltp" in data
    assert "olap" in data
    assert "pipeline" in data


def test_catalog_endpoints():
    p_resp = client.get("/api/catalog/products")
    assert p_resp.status_code == 200
    assert len(p_resp.json()["products"]) > 0

    c_resp = client.get("/api/catalog/customers")
    assert c_resp.status_code == 200
    assert len(c_resp.json()["customers"]) > 0


def test_place_order_and_sync():
    products = client.get("/api/catalog/products").json()["products"]
    customers = client.get("/api/catalog/customers").json()["customers"]

    payload = {
        "customer_id": customers[0]["id"],
        "items": [
            {"product_id": products[0]["id"], "quantity": 1, "discount_amount": 0.0}
        ],
        "payment_method": "Apple Pay",
        "shipping_country": "US",
        "order_status": "PAID",
    }
    order_resp = client.post("/api/orders", json=payload)
    assert order_resp.status_code == 200
    assert order_resp.json()["order"]["order_id"] > 0

    # Sync
    sync_resp = client.post("/api/pipeline/sync", json={"batch_size": 100})
    assert sync_resp.status_code == 200
    assert sync_resp.json()["status"] in ["SUCCESS", "NO_OP"]


def test_analytics_endpoints():
    overview = client.get("/api/analytics/overview")
    assert overview.status_code == 200
    assert "gmv" in overview.json()

    trends = client.get("/api/analytics/trends")
    assert trends.status_code == 200

    categories = client.get("/api/analytics/categories")
    assert categories.status_code == 200


def test_benchmark_run():
    resp = client.post("/api/benchmark/run", json={"query_type": "category_revenue"})
    assert resp.status_code == 200
    data = resp.json()
    assert "speedup_factor" in data["comparison"]
