"""FastAPI Application for E-Commerce OLTP to OLAP System Architecture Lab."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.database import (
    create_order,
    get_customers,
    get_oltp_stats,
    get_products,
    get_recent_orders,
    init_db,
)
from app.clickhouse import (
    get_analytics_overview,
    get_category_distribution,
    get_customer_segment_distribution,
    get_olap_stats,
    get_regional_distribution,
    get_sales_trends,
    init_clickhouse,
)
from app.pipeline import (
    get_pipeline_telemetry,
    run_pipeline_sync,
    set_auto_sync_state,
)
from app.generator import simulate_orders_batch
from app.benchmark import BENCHMARK_DESCRIPTIONS, run_comparison_benchmark

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize databases
    init_db()
    init_clickhouse()

    # Pre-seed initial sample orders and sync if database is fresh
    try:
        oltp_stats = get_oltp_stats()
        if oltp_stats["total_orders"] < 20:
            simulate_orders_batch(count=35)
            run_pipeline_sync(batch_size=500)
    except Exception as exc:
        print(f"Warning during initial seed: {exc}")

    yield

    # Shutdown: Stop any background workers
    set_auto_sync_state(False)


app = FastAPI(
    title="E-Commerce OLTP to OLAP System Architecture Lab",
    description="Interactive demonstration of dual-database architecture: PostgreSQL (OLTP) -> ETL / ELT -> ClickHouse (OLAP) -> BI Dashboard.",
    version="1.0.0",
    lifespan=lifespan,
)


# --- HTML Page Routes ---
@app.get("/", response_class=RedirectResponse)
def root_redirect():
    return RedirectResponse(url="/dashboard", status_code=307)


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/demo", response_class=HTMLResponse)
def get_dashboard_page():
    demo_file = BASE_DIR / "demo.html"
    if not demo_file.exists():
        raise HTTPException(status_code=404, detail="demo.html not found.")
    return FileResponse(demo_file)


@app.get("/architecture", response_class=HTMLResponse)
def get_architecture_page():
    arch_file = BASE_DIR / "architecture.html"
    if not arch_file.exists():
        raise HTTPException(status_code=404, detail="architecture.html not found.")
    return FileResponse(arch_file)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    oltp = get_oltp_stats()
    olap = get_olap_stats()
    return {
        "status": "ready",
        "oltp_engine": oltp["engine"],
        "olap_engine": olap["engine"],
    }


# --- Cluster & Environment Status ---
@app.get("/api/cluster/status")
def get_cluster_status():
    oltp = get_oltp_stats()
    olap = get_olap_stats()
    pipeline = get_pipeline_telemetry()
    return {
        "oltp": oltp,
        "olap": olap,
        "pipeline": {
            "un_synced_backlog_orders": pipeline["un_synced_backlog_orders"],
            "total_records_synced": pipeline["total_records_synced"],
            "auto_sync_enabled": pipeline["auto_sync_enabled"],
        },
    }


# --- Storefront / Product Catalog ---
@app.get("/api/catalog/products")
def list_products():
    return {"products": get_products()}


@app.get("/api/catalog/customers")
def list_customers():
    return {"customers": get_customers()}


# --- OLTP Orders & Transaction API ---
class OrderItemPayload(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1, le=100)
    discount_amount: float = Field(0.0, ge=0.0)


class CreateOrderRequest(BaseModel):
    customer_id: int
    items: List[OrderItemPayload]
    payment_method: str = "Credit Card"
    shipping_country: Optional[str] = None
    order_status: str = "PAID"


@app.post("/api/orders")
def place_order(payload: CreateOrderRequest):
    try:
        items_dict = [it.model_dump() for it in payload.items]
        res = create_order(
            customer_id=payload.customer_id,
            items=items_dict,
            payment_method=payload.payment_method,
            shipping_country=payload.shipping_country,
            order_status=payload.order_status,
        )
        return {"status": "success", "order": res}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/orders/recent")
def list_recent_orders(limit: int = 20):
    return {"orders": get_recent_orders(limit=limit)}


class SimulateBatchRequest(BaseModel):
    count: int = Field(50, ge=1, le=5000)


@app.post("/api/orders/simulate")
def simulate_orders(payload: SimulateBatchRequest):
    try:
        summary = simulate_orders_batch(count=payload.count)
        return {"status": "success", "summary": summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# --- ETL / ELT Pipeline Controller ---
class SyncRequest(BaseModel):
    batch_size: int = Field(500, ge=10, le=10000)


@app.post("/api/pipeline/sync")
def trigger_sync(payload: SyncRequest):
    try:
        summary = run_pipeline_sync(batch_size=payload.batch_size)
        return summary
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/pipeline/status")
def pipeline_status():
    return get_pipeline_telemetry()


class AutoSyncToggleRequest(BaseModel):
    enabled: bool
    interval_sec: float = Field(3.0, ge=1.0, le=60.0)


@app.post("/api/pipeline/autoloop")
def toggle_auto_sync(payload: AutoSyncToggleRequest):
    new_state = set_auto_sync_state(payload.enabled, payload.interval_sec)
    return {"auto_sync_enabled": new_state, "interval_sec": payload.interval_sec}


# --- ClickHouse OLAP BI Analytics API ---
@app.get("/api/analytics/overview")
def analytics_overview():
    return get_analytics_overview()


@app.get("/api/analytics/trends")
def analytics_trends():
    return {"trends": get_sales_trends()}


@app.get("/api/analytics/categories")
def analytics_categories():
    return {"categories": get_category_distribution()}


@app.get("/api/analytics/regions")
def analytics_regions():
    return {"regions": get_regional_distribution()}


@app.get("/api/analytics/segments")
def analytics_segments():
    return {"segments": get_customer_segment_distribution()}


# --- Performance Benchmark API ---
class BenchmarkRequest(BaseModel):
    query_type: str = Field("category_revenue", description="Benchmark query identifier")


@app.post("/api/benchmark/run")
def run_benchmark(payload: BenchmarkRequest):
    try:
        res = run_comparison_benchmark(payload.query_type)
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/benchmark/types")
def get_benchmark_types():
    return {"types": BENCHMARK_DESCRIPTIONS}
