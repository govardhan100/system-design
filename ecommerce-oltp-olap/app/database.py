"""PostgreSQL OLTP Database Engine & Abstraction Layer.

Handles ACID transactions for customer checkout, order placement,
normalized table queries, sync checkpoint tracking, and simulated
OLTP analytical scans for comparison benchmarks.
Supports transparent SQLite fallback if PostgreSQL is unavailable.
"""

import os
import sqlite3
import time
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("oltp.database")

# Environment / Connection Variables
PG_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5434"))
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")
PG_DB = os.getenv("POSTGRES_DB", "ecommerce_oltp")

# Global driver flag
USE_POSTGRES = False
_sqlite_conn: Optional[sqlite3.Connection] = None
_psycopg_available = False

try:
    import psycopg
    from psycopg.rows import dict_row
    _psycopg_available = True
except ImportError:
    psycopg = None
    dict_row = None


def get_pg_connection_string() -> str:
    return f"host={PG_HOST} port={PG_PORT} user={PG_USER} password={PG_PASS} dbname={PG_DB} connect_timeout=3"


def test_postgres_connection() -> bool:
    """Check if PostgreSQL container is up and accessible."""
    global USE_POSTGRES
    if not _psycopg_available:
        USE_POSTGRES = False
        return False
    try:
        conn = psycopg.connect(get_pg_connection_string(), autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        USE_POSTGRES = True
        return True
    except Exception as exc:
        logger.warning("PostgreSQL not reachable (%s). Using in-memory OLTP fallback.", exc)
        USE_POSTGRES = False
        return False


def get_sqlite_conn() -> sqlite3.Connection:
    """Get persistent in-process SQLite connection for fallback mode."""
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        _sqlite_conn.row_factory = sqlite3.Row
        _init_sqlite_schema(_sqlite_conn)
    return _sqlite_conn


def _init_sqlite_schema(conn: sqlite3.Connection):
    """Initialize schema for SQLite fallback mode."""
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        segment TEXT NOT NULL DEFAULT 'Regular',
        country TEXT NOT NULL DEFAULT 'US',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        price REAL NOT NULL,
        cost REAL NOT NULL,
        stock_quantity INTEGER NOT NULL DEFAULT 500,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL REFERENCES customers(id),
        order_status TEXT NOT NULL DEFAULT 'PAID',
        payment_method TEXT NOT NULL DEFAULT 'Credit Card',
        shipping_country TEXT NOT NULL DEFAULT 'US',
        total_amount REAL NOT NULL DEFAULT 0.00,
        currency TEXT NOT NULL DEFAULT 'USD',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        unit_price REAL NOT NULL,
        cost_price REAL NOT NULL,
        discount_amount REAL NOT NULL DEFAULT 0.00,
        line_total REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sync_checkpoint (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pipeline_name TEXT UNIQUE NOT NULL,
        last_synced_order_id INTEGER NOT NULL DEFAULT 0,
        last_synced_timestamp TEXT DEFAULT '1970-01-01 00:00:00',
        total_records_synced INTEGER NOT NULL DEFAULT 0,
        last_sync_duration_ms REAL DEFAULT 0.0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    INSERT OR IGNORE INTO sync_checkpoint (pipeline_name, last_synced_order_id, last_synced_timestamp, total_records_synced)
    VALUES ('ecommerce_clickhouse_elt', 0, '1970-01-01 00:00:00', 0);
    """)

    # Check if products exist, seed if empty
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        products = [
            ('Ultra-HD 4K Noise Canceling Headphones', 'Electronics', 299.99, 140.00, 250),
            ('Mechanical Ergonomic RGB Keyboard', 'Electronics', 149.50, 65.00, 300),
            ('Curved Gaming Monitor 34-inch 144Hz', 'Electronics', 499.00, 260.00, 120),
            ('Smart Fitness Tracker Band 5', 'Electronics', 79.99, 32.00, 450),
            ('USB-C 100W GaN Fast Charger', 'Electronics', 45.00, 16.50, 600),
            ('Organic Cotton Heavyweight Hoodie', 'Apparel', 89.00, 28.00, 400),
            ('Waterproof Trail Running Shoes', 'Apparel', 135.00, 52.00, 220),
            ('Merino Wool Minimalist Beanie', 'Apparel', 34.00, 11.00, 350),
            ('Thermal Insulation Winter Jacket', 'Apparel', 195.00, 75.00, 180),
            ('Breathable Mesh Athletic Shorts', 'Apparel', 42.00, 14.00, 500),
            ('Precision Barista Espresso Machine', 'Home & Kitchen', 649.00, 310.00, 80),
            ('Cast Iron Enameled Dutch Oven 6-Qt', 'Home & Kitchen', 119.00, 45.00, 190),
            ('Japanese Steel Chef Knife 8-Inch', 'Home & Kitchen', 85.00, 30.00, 260),
            ('Smart WiFi Convection Air Fryer', 'Home & Kitchen', 129.99, 55.00, 210),
            ('Double-Walled Stainless Steel Tumbler', 'Home & Kitchen', 29.50, 9.00, 800),
            ('Pro Carbon Fiber Road Bicycle Frame', 'Sports', 890.00, 420.00, 40),
            ('Adjustable Dumbbell Set (5-50 lbs)', 'Sports', 320.00, 145.00, 95),
            ('High-Density Non-Slip Yoga Mat', 'Sports', 48.00, 16.00, 400),
            ('Ultra-Lightweight 2-Person Backpacking Tent', 'Sports', 229.00, 95.00, 110),
            ('System Design Interview Handbook Vol. 1', 'Books', 39.99, 12.00, 600),
            ('Designing Data-Intensive Applications', 'Books', 49.99, 15.00, 750),
            ('Distributed Systems in Practice', 'Books', 44.50, 14.00, 550)
        ]
        cur.executemany("INSERT INTO products (name, category, price, cost, stock_quantity) VALUES (?, ?, ?, ?, ?)", products)

    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        customers = [
            ('Alex Mercer', 'alex.mercer@example.com', 'VIP', 'US'),
            ('Sophia Chen', 'sophia.chen@example.com', 'VIP', 'US'),
            ('Liam O''Connor', 'liam.oc@example.com', 'Regular', 'UK'),
            ('Emma Dubois', 'emma.dubois@example.com', 'Regular', 'FR'),
            ('Lucas Müller', 'lucas.muller@example.com', 'VIP', 'DE'),
            ('Yuki Tanaka', 'yuki.tanaka@example.com', 'Regular', 'JP'),
            ('Mateo Silva', 'mateo.silva@example.com', 'New', 'BR'),
            ('Aarav Patel', 'aarav.patel@example.com', 'VIP', 'IN'),
            ('Chloe Martin', 'chloe.martin@example.com', 'Regular', 'CA'),
            ('Daniel Kim', 'daniel.kim@example.com', 'At-Risk', 'US'),
            ('Elena Rossi', 'elena.rossi@example.com', 'Regular', 'DE'),
            ('Noah Johnson', 'noah.j@example.com', 'New', 'US'),
            ('Mia Williams', 'mia.w@example.com', 'Regular', 'UK'),
            ('Ethan Brown', 'ethan.b@example.com', 'VIP', 'CA'),
            ('Olivia Garcia', 'olivia.g@example.com', 'Regular', 'US')
        ]
        cur.executemany("INSERT INTO customers (name, email, segment, country) VALUES (?, ?, ?, ?)", customers)

    conn.commit()


@contextmanager
def get_db_cursor():
    """Context manager yielding a cursor for database operations."""
    global USE_POSTGRES
    if USE_POSTGRES and _psycopg_available:
        try:
            conn = psycopg.connect(get_pg_connection_string(), row_factory=dict_row)
            try:
                with conn.cursor() as cur:
                    yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return
        except Exception as exc:
            logger.warning("Postgres query failed (%s), falling back to SQLite", exc)
            USE_POSTGRES = False

    conn = get_sqlite_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    """Verify and initialize database connection."""
    test_postgres_connection()
    if not USE_POSTGRES:
        get_sqlite_conn()
        logger.info("Initialized OLTP Database with SQLite In-Memory Engine")
    else:
        logger.info("Connected to PostgreSQL OLTP Database on %s:%s", PG_HOST, PG_PORT)


def get_products() -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT id, name, category, price, cost, stock_quantity, is_active FROM products WHERE is_active = TRUE or is_active = 1 ORDER BY category, name")
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def get_customers() -> List[Dict[str, Any]]:
    with get_db_cursor() as cur:
        cur.execute("SELECT id, name, email, segment, country FROM customers ORDER BY id LIMIT 100")
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def create_order(
    customer_id: int,
    items: List[Dict[str, Any]],
    payment_method: str = "Credit Card",
    shipping_country: Optional[str] = None,
    order_status: str = "PAID",
) -> Dict[str, Any]:
    """Execute an ACID OLTP transaction to place an order and update inventory."""
    if not items:
        raise ValueError("Order must contain at least one line item.")

    with get_db_cursor() as cur:
        # Resolve customer shipping country if not provided
        if not shipping_country:
            cur.execute("SELECT country FROM customers WHERE id = %s" if USE_POSTGRES else "SELECT country FROM customers WHERE id = ?", (customer_id,))
            row = cur.fetchone()
            shipping_country = row["country"] if row else "US"

        # Calculate totals and line items
        total_order_amount = 0.0
        line_items_data = []

        for it in items:
            p_id = it["product_id"]
            qty = int(it.get("quantity", 1))
            discount = float(it.get("discount_amount", 0.0))

            cur.execute("SELECT price, cost, stock_quantity FROM products WHERE id = %s" if USE_POSTGRES else "SELECT price, cost, stock_quantity FROM products WHERE id = ?", (p_id,))
            p_row = cur.fetchone()
            if not p_row:
                raise ValueError(f"Product {p_id} not found.")

            price = float(p_row["price"])
            cost = float(p_row["cost"])
            line_total = max(0.0, (price * qty) - discount)
            total_order_amount += line_total

            line_items_data.append({
                "product_id": p_id,
                "quantity": qty,
                "unit_price": price,
                "cost_price": cost,
                "discount_amount": discount,
                "line_total": round(line_total, 2)
            })

            # Inventory decrement
            cur.execute(
                "UPDATE products SET stock_quantity = stock_quantity - %s WHERE id = %s" if USE_POSTGRES else "UPDATE products SET stock_quantity = stock_quantity - ? WHERE id = ?",
                (qty, p_id)
            )

        # Insert Order header
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if USE_POSTGRES:
            cur.execute(
                """
                INSERT INTO orders (customer_id, order_status, payment_method, shipping_country, total_amount, currency, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'USD', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id, created_at
                """,
                (customer_id, order_status, payment_method, shipping_country, round(total_order_amount, 2))
            )
            ret = cur.fetchone()
            order_id = ret["id"]
            created_at = ret["created_at"]
        else:
            cur.execute(
                """
                INSERT INTO orders (customer_id, order_status, payment_method, shipping_country, total_amount, currency, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'USD', ?, ?)
                """,
                (customer_id, order_status, payment_method, shipping_country, round(total_order_amount, 2), now_iso, now_iso)
            )
            order_id = cur.lastrowid
            created_at = now_iso

        # Insert Order Items
        for li in line_items_data:
            if USE_POSTGRES:
                cur.execute(
                    """
                    INSERT INTO order_items (order_id, product_id, quantity, unit_price, cost_price, discount_amount, line_total)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (order_id, li["product_id"], li["quantity"], li["unit_price"], li["cost_price"], li["discount_amount"], li["line_total"])
                )
            else:
                cur.execute(
                    """
                    INSERT INTO order_items (order_id, product_id, quantity, unit_price, cost_price, discount_amount, line_total)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (order_id, li["product_id"], li["quantity"], li["unit_price"], li["cost_price"], li["discount_amount"], li["line_total"])
                )

        return {
            "order_id": order_id,
            "customer_id": customer_id,
            "order_status": order_status,
            "payment_method": payment_method,
            "shipping_country": shipping_country,
            "total_amount": round(total_order_amount, 2),
            "created_at": str(created_at),
            "items_count": len(line_items_data),
        }


def get_recent_orders(limit: int = 15) -> List[Dict[str, Any]]:
    """Retrieve recent orders with joined customer name and items count for OLTP inspector."""
    with get_db_cursor() as cur:
        q = """
        SELECT 
            o.id AS order_id,
            o.customer_id,
            c.name AS customer_name,
            c.segment AS customer_segment,
            o.order_status,
            o.payment_method,
            o.shipping_country,
            o.total_amount,
            o.created_at,
            COUNT(oi.id) AS items_count
        FROM orders o
        JOIN customers c ON o.customer_id = c.id
        LEFT JOIN order_items oi ON o.id = oi.order_id
        GROUP BY o.id, o.customer_id, c.name, c.segment, o.order_status, o.payment_method, o.shipping_country, o.total_amount, o.created_at
        ORDER BY o.id DESC
        LIMIT %s
        """ if USE_POSTGRES else """
        SELECT 
            o.id AS order_id,
            o.customer_id,
            c.name AS customer_name,
            c.segment AS customer_segment,
            o.order_status,
            o.payment_method,
            o.shipping_country,
            o.total_amount,
            o.created_at,
            COUNT(oi.id) AS items_count
        FROM orders o
        JOIN customers c ON o.customer_id = c.id
        LEFT JOIN order_items oi ON o.id = oi.order_id
        GROUP BY o.id, o.customer_id, c.name, c.segment, o.order_status, o.payment_method, o.shipping_country, o.total_amount, o.created_at
        ORDER BY o.id DESC
        LIMIT ?
        """
        cur.execute(q, (limit,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def get_sync_checkpoint(pipeline_name: str = "ecommerce_clickhouse_elt") -> Dict[str, Any]:
    with get_db_cursor() as cur:
        q = "SELECT last_synced_order_id, last_synced_timestamp, total_records_synced, last_sync_duration_ms, updated_at FROM sync_checkpoint WHERE pipeline_name = %s" if USE_POSTGRES else "SELECT last_synced_order_id, last_synced_timestamp, total_records_synced, last_sync_duration_ms, updated_at FROM sync_checkpoint WHERE pipeline_name = ?"
        cur.execute(q, (pipeline_name,))
        row = cur.fetchone()
        if row:
            return dict(row)
        return {
            "last_synced_order_id": 0,
            "last_synced_timestamp": "1970-01-01 00:00:00",
            "total_records_synced": 0,
            "last_sync_duration_ms": 0.0,
            "updated_at": "1970-01-01 00:00:00",
        }


def update_sync_checkpoint(
    pipeline_name: str,
    last_order_id: int,
    records_synced: int,
    duration_ms: float,
):
    with get_db_cursor() as cur:
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if USE_POSTGRES:
            cur.execute(
                """
                UPDATE sync_checkpoint
                SET last_synced_order_id = %s,
                    last_synced_timestamp = CURRENT_TIMESTAMP,
                    total_records_synced = total_records_synced + %s,
                    last_sync_duration_ms = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE pipeline_name = %s
                """,
                (last_order_id, records_synced, duration_ms, pipeline_name)
            )
        else:
            cur.execute(
                """
                UPDATE sync_checkpoint
                SET last_synced_order_id = ?,
                    last_synced_timestamp = ?,
                    total_records_synced = total_records_synced + ?,
                    last_sync_duration_ms = ?,
                    updated_at = ?
                WHERE pipeline_name = ?
                """,
                (last_order_id, now_iso, records_synced, duration_ms, now_iso, pipeline_name)
            )


def extract_unsynced_order_records(last_order_id: int, limit: int = 500) -> List[Dict[str, Any]]:
    """Extract and denormalize order items from relational OLTP for ClickHouse loading."""
    with get_db_cursor() as cur:
        q = """
        SELECT 
            o.id AS order_id,
            oi.id AS item_id,
            o.created_at AS order_timestamp,
            c.id AS customer_id,
            c.name AS customer_name,
            c.segment AS customer_segment,
            o.shipping_country AS customer_country,
            p.id AS product_id,
            p.name AS product_name,
            p.category,
            oi.quantity,
            oi.unit_price,
            oi.cost_price,
            oi.discount_amount,
            oi.line_total,
            (oi.line_total - (oi.cost_price * oi.quantity)) AS profit,
            o.payment_method,
            o.order_status
        FROM orders o
        JOIN customers c ON o.customer_id = c.id
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        WHERE o.id > %s
        ORDER BY o.id ASC, oi.id ASC
        LIMIT %s
        """ if USE_POSTGRES else """
        SELECT 
            o.id AS order_id,
            oi.id AS item_id,
            o.created_at AS order_timestamp,
            c.id AS customer_id,
            c.name AS customer_name,
            c.segment AS customer_segment,
            o.shipping_country AS customer_country,
            p.id AS product_id,
            p.name AS product_name,
            p.category,
            oi.quantity,
            oi.unit_price,
            oi.cost_price,
            oi.discount_amount,
            oi.line_total,
            (oi.line_total - (oi.cost_price * oi.quantity)) AS profit,
            o.payment_method,
            o.order_status
        FROM orders o
        JOIN customers c ON o.customer_id = c.id
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        WHERE o.id > ?
        ORDER BY o.id ASC, oi.id ASC
        LIMIT ?
        """
        cur.execute(q, (last_order_id, limit))
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def get_oltp_stats() -> Dict[str, Any]:
    with get_db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total_orders FROM orders")
        tot_orders = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) AS total_items FROM order_items")
        tot_items = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(total_amount), 0.0) AS total_revenue FROM orders")
        tot_rev = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) AS total_customers FROM customers")
        tot_cust = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) AS total_products FROM products")
        tot_prod = cur.fetchone()[0]

        return {
            "engine": "PostgreSQL 17 (Docker OLTP)" if USE_POSTGRES else "SQLite In-Memory (Fallback)",
            "is_postgres": USE_POSTGRES,
            "total_orders": int(tot_orders),
            "total_items": int(tot_items),
            "total_revenue": round(float(tot_rev), 2),
            "total_customers": int(tot_cust),
            "total_products": int(tot_prod),
        }


def run_oltp_benchmark_query(query_type: str) -> Dict[str, Any]:
    """Execute row-oriented analytical query on PostgreSQL / normalized schema to demonstrate row-scan overhead."""
    start_t = time.perf_counter()
    with get_db_cursor() as cur:
        if query_type == "category_revenue":
            sql = """
            SELECT 
                p.category,
                COUNT(DISTINCT o.id) AS orders_count,
                SUM(oi.quantity) AS total_units,
                ROUND(SUM(oi.line_total)::numeric, 2) AS total_revenue,
                ROUND(SUM(oi.line_total - (oi.cost_price * oi.quantity))::numeric, 2) AS total_profit,
                ROUND(AVG(oi.line_total)::numeric, 2) AS avg_item_value
            FROM orders o
            JOIN order_items oi ON o.id = oi.order_id
            JOIN products p ON oi.product_id = p.id
            GROUP BY p.category
            ORDER BY total_revenue DESC
            """ if USE_POSTGRES else """
            SELECT 
                p.category,
                COUNT(DISTINCT o.id) AS orders_count,
                SUM(oi.quantity) AS total_units,
                ROUND(SUM(oi.line_total), 2) AS total_revenue,
                ROUND(SUM(oi.line_total - (oi.cost_price * oi.quantity)), 2) AS total_profit,
                ROUND(AVG(oi.line_total), 2) AS avg_item_value
            FROM orders o
            JOIN order_items oi ON o.id = oi.order_id
            JOIN products p ON oi.product_id = p.id
            GROUP BY p.category
            ORDER BY total_revenue DESC
            """
        elif query_type == "segment_metrics":
            sql = """
            SELECT 
                c.segment,
                c.country,
                COUNT(DISTINCT o.id) AS orders_count,
                ROUND(SUM(o.total_amount)::numeric, 2) AS gmv,
                ROUND(AVG(o.total_amount)::numeric, 2) AS aov
            FROM orders o
            JOIN customers c ON o.customer_id = c.id
            GROUP BY c.segment, c.country
            ORDER BY gmv DESC
            LIMIT 10
            """ if USE_POSTGRES else """
            SELECT 
                c.segment,
                c.country,
                COUNT(DISTINCT o.id) AS orders_count,
                ROUND(SUM(o.total_amount), 2) AS gmv,
                ROUND(AVG(o.total_amount), 2) AS aov
            FROM orders o
            JOIN customers c ON o.customer_id = c.id
            GROUP BY c.segment, c.country
            ORDER BY gmv DESC
            LIMIT 10
            """
        elif query_type == "monthly_trend":
            sql = """
            SELECT 
                TO_CHAR(o.created_at, 'YYYY-MM') AS month_period,
                COUNT(DISTINCT o.id) AS orders_count,
                ROUND(SUM(o.total_amount)::numeric, 2) AS monthly_revenue
            FROM orders o
            GROUP BY TO_CHAR(o.created_at, 'YYYY-MM')
            ORDER BY month_period ASC
            """ if USE_POSTGRES else """
            SELECT 
                SUBSTR(o.created_at, 1, 7) AS month_period,
                COUNT(DISTINCT o.id) AS orders_count,
                ROUND(SUM(o.total_amount), 2) AS monthly_revenue
            FROM orders o
            GROUP BY SUBSTR(o.created_at, 1, 7)
            ORDER BY month_period ASC
            """
        else:
            # Complex multi-filter
            sql = """
            SELECT 
                p.name AS product_name,
                p.category,
                SUM(oi.quantity) AS units_sold,
                ROUND(SUM(oi.line_total)::numeric, 2) AS revenue
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN products p ON oi.product_id = p.id
            WHERE o.order_status = 'PAID' AND oi.discount_amount > 0
            GROUP BY p.name, p.category
            ORDER BY units_sold DESC
            LIMIT 5
            """ if USE_POSTGRES else """
            SELECT 
                p.name AS product_name,
                p.category,
                SUM(oi.quantity) AS units_sold,
                ROUND(SUM(oi.line_total), 2) AS revenue
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN products p ON oi.product_id = p.id
            WHERE o.order_status = 'PAID' AND oi.discount_amount > 0
            GROUP BY p.name, p.category
            ORDER BY units_sold DESC
            LIMIT 5
            """

        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]

    duration_ms = round((time.perf_counter() - start_t) * 1000, 3)
    return {
        "engine": "PostgreSQL (OLTP Row-Scan)" if USE_POSTGRES else "SQLite Row-Scan",
        "query_type": query_type,
        "duration_ms": duration_ms,
        "rows_returned": len(rows),
        "results": rows,
        "storage_paradigm": "Row-oriented (B-tree / Table Sequential Scan with Hash/Nested Loop Joins)",
    }
