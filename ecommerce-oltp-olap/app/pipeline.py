"""ETL / ELT Pipeline Engine for E-Commerce Data Synchronization.

Extracts normalized relational transactions from PostgreSQL OLTP,
transforms & denormalizes into wide analytical event facts with derived profit metrics,
and loads into ClickHouse OLAP with high-water mark checkpoints and idempotency.
"""

import asyncio
import time
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from app.database import (
    extract_unsynced_order_records,
    get_sync_checkpoint,
    update_sync_checkpoint,
)
from app.clickhouse import insert_sales_facts

logger = logging.getLogger("pipeline.etl")

# In-memory execution ledger for live pipeline telemetry in UI
_sync_history: Deque[Dict[str, Any]] = deque(maxlen=30)
_auto_sync_task: Optional[asyncio.Task] = None
_auto_sync_enabled: bool = False
_auto_sync_interval: float = 3.0


def run_pipeline_sync(batch_size: int = 500) -> Dict[str, Any]:
    """Execute a single incremental ETL / ELT batch sync."""
    start_time = time.perf_counter()

    # Step 1: Read High-Water Mark Checkpoint
    checkpoint = get_sync_checkpoint("ecommerce_clickhouse_elt")
    last_order_id = checkpoint["last_synced_order_id"]

    # Step 2: EXTRACT from PostgreSQL OLTP
    raw_records = extract_unsynced_order_records(last_order_id=last_order_id, limit=batch_size)
    extracted_count = len(raw_records)

    if extracted_count == 0:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        summary = {
            "status": "NO_OP",
            "message": "All orders are up to date in OLAP. No new records to sync.",
            "extracted": 0,
            "transformed": 0,
            "loaded": 0,
            "duration_ms": duration_ms,
            "throughput_rps": 0,
            "last_order_id": last_order_id,
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        }
        _sync_history.appendleft(summary)
        return summary

    # Step 3: TRANSFORM & Enrich into Denormalized Analytical Schema
    transformed_records = []
    max_order_id = last_order_id

    for r in raw_records:
        cur_order_id = int(r["order_id"])
        if cur_order_id > max_order_id:
            max_order_id = cur_order_id

        # Calculate accurate profit and format timestamps
        qty = int(r["quantity"])
        unit_p = float(r["unit_price"])
        cost_p = float(r["cost_price"])
        line_tot = float(r["line_total"])
        disc = float(r.get("discount_amount", 0.0))
        computed_profit = round(line_tot - (cost_p * qty), 2)

        raw_ts = str(r["order_timestamp"])
        transformed = {
            "order_id": cur_order_id,
            "item_id": int(r["item_id"]),
            "order_timestamp": raw_ts,
            "order_date": raw_ts[:10] if len(raw_ts) >= 10 else "2026-01-01",
            "customer_id": int(r["customer_id"]),
            "customer_name": str(r["customer_name"]).strip(),
            "customer_segment": str(r["customer_segment"]),
            "customer_country": str(r["customer_country"]),
            "product_id": int(r["product_id"]),
            "product_name": str(r["product_name"]),
            "category": str(r["category"]),
            "quantity": qty,
            "unit_price": unit_p,
            "cost_price": cost_p,
            "discount_amount": disc,
            "line_total": line_tot,
            "profit": computed_profit,
            "payment_method": str(r["payment_method"]),
            "order_status": str(r["order_status"]),
        }
        transformed_records.append(transformed)

    transformed_count = len(transformed_records)

    # Step 4: LOAD into ClickHouse OLAP
    loaded_count = insert_sales_facts(transformed_records)

    # Step 5: Update OLTP High-Water Mark Checkpoint atomically
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    update_sync_checkpoint(
        pipeline_name="ecommerce_clickhouse_elt",
        last_order_id=max_order_id,
        records_synced=loaded_count,
        duration_ms=duration_ms,
    )

    throughput = round((loaded_count / (duration_ms / 1000.0)), 1) if duration_ms > 0 else loaded_count

    summary = {
        "status": "SUCCESS",
        "message": f"Successfully moved & transformed {loaded_count} records into ClickHouse.",
        "extracted": extracted_count,
        "transformed": transformed_count,
        "loaded": loaded_count,
        "duration_ms": duration_ms,
        "throughput_rps": throughput,
        "last_order_id": max_order_id,
        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
    }
    _sync_history.appendleft(summary)
    return summary


def get_pipeline_telemetry() -> Dict[str, Any]:
    """Retrieve current pipeline status, sync log, and lag metrics."""
    checkpoint = get_sync_checkpoint("ecommerce_clickhouse_elt")
    last_synced_id = checkpoint["last_synced_order_id"]

    # Check un-synced backlog in OLTP
    from app.database import get_db_cursor, USE_POSTGRES
    backlog_count = 0
    with get_db_cursor() as cur:
        q = "SELECT COUNT(*) FROM orders WHERE id > %s" if USE_POSTGRES else "SELECT COUNT(*) FROM orders WHERE id > ?"
        cur.execute(q, (last_synced_id,))
        backlog_count = int(cur.fetchone()[0])

    return {
        "pipeline_name": "PostgreSQL -> ClickHouse ETL/ELT",
        "auto_sync_enabled": _auto_sync_enabled,
        "auto_sync_interval_sec": _auto_sync_interval,
        "last_synced_order_id": last_synced_id,
        "last_synced_timestamp": str(checkpoint["last_synced_timestamp"]),
        "total_records_synced": checkpoint["total_records_synced"],
        "last_sync_duration_ms": checkpoint["last_sync_duration_ms"],
        "un_synced_backlog_orders": backlog_count,
        "recent_syncs": list(_sync_history),
    }


async def _auto_sync_loop():
    """Background task polling for un-synced orders."""
    global _auto_sync_enabled
    logger.info("Starting background ETL auto-sync loop (interval=%.1fs)...", _auto_sync_interval)
    while _auto_sync_enabled:
        try:
            run_pipeline_sync(batch_size=1000)
        except Exception as exc:
            logger.error("Auto-sync loop error: %s", exc)
        await asyncio.sleep(_auto_sync_interval)


def set_auto_sync_state(enabled: bool, interval: float = 3.0) -> bool:
    """Enable or disable background auto-sync loop."""
    global _auto_sync_enabled, _auto_sync_task, _auto_sync_interval
    _auto_sync_interval = max(1.0, interval)
    _auto_sync_enabled = enabled

    if enabled:
        if _auto_sync_task is None or _auto_sync_task.done():
            loop = asyncio.get_event_loop()
            _auto_sync_task = loop.create_task(_auto_sync_loop())
    else:
        if _auto_sync_task and not _auto_sync_task.done():
            _auto_sync_task.cancel()
            _auto_sync_task = None

    return _auto_sync_enabled
