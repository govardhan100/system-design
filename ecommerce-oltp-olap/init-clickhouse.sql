-- ClickHouse Schema for E-Commerce OLAP Analytical Warehouse
-- Optimized for high-throughput columnar vector scans, SIMD aggregations, and sub-millisecond BI queries.

CREATE DATABASE IF NOT EXISTS analytics;

-- Analytical Denormalized Fact Table
-- Uses ReplacingMergeTree so that re-synced or updated orders are deduplicated on primary key
CREATE TABLE IF NOT EXISTS analytics.sales_fact (
    order_id UInt64,
    item_id UInt64,
    order_date Date,
    order_timestamp DateTime,
    customer_id UInt32,
    customer_name String,
    customer_segment LowCardinality(String),
    customer_country LowCardinality(String),
    product_id UInt32,
    product_name String,
    category LowCardinality(String),
    quantity UInt32,
    unit_price Float64,
    cost_price Float64,
    discount_amount Float64,
    line_total Float64,
    profit Float64,
    payment_method LowCardinality(String),
    order_status LowCardinality(String),
    synced_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(synced_at)
PARTITION BY toYYYYMM(order_date)
ORDER BY (category, order_date, customer_id, order_id, item_id)
SETTINGS index_granularity = 8192;

-- Target Table for Materialized Aggregate Projections
CREATE TABLE IF NOT EXISTS analytics.daily_category_stats (
    order_date Date,
    category LowCardinality(String),
    order_count UInt64,
    item_count UInt64,
    gross_revenue Float64,
    net_profit Float64
)
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(order_date)
ORDER BY (category, order_date);

-- Materialized View that maintains real-time aggregates during ingestion
CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.daily_category_mv
TO analytics.daily_category_stats AS
SELECT
    order_date,
    category,
    countDistinct(order_id) AS order_count,
    sum(quantity) AS item_count,
    sum(line_total) AS gross_revenue,
    sum(profit) AS net_profit
FROM analytics.sales_fact
GROUP BY order_date, category;
