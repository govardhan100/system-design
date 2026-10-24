-- PostgreSQL Schema for E-Commerce OLTP Database
-- Optimized for high-throughput ACID transactions, normalized relational consistency (3NF), and point lookups.

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    segment VARCHAR(30) NOT NULL DEFAULT 'Regular', -- VIP, Regular, New, At-Risk
    country VARCHAR(10) NOT NULL DEFAULT 'US',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    category VARCHAR(60) NOT NULL, -- Electronics, Apparel, Home & Kitchen, Sports, Books
    price NUMERIC(10, 2) NOT NULL,
    cost NUMERIC(10, 2) NOT NULL,
    stock_quantity INT NOT NULL DEFAULT 500,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(id),
    order_status VARCHAR(30) NOT NULL DEFAULT 'PAID', -- PENDING, PAID, SHIPPED, DELIVERED, CANCELLED
    payment_method VARCHAR(40) NOT NULL DEFAULT 'Credit Card', -- Credit Card, PayPal, Apple Pay, Crypto, Wire
    shipping_country VARCHAR(10) NOT NULL DEFAULT 'US',
    total_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES products(id),
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL,
    cost_price NUMERIC(10, 2) NOT NULL,
    discount_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    line_total NUMERIC(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_checkpoint (
    id SERIAL PRIMARY KEY,
    pipeline_name VARCHAR(50) UNIQUE NOT NULL,
    last_synced_order_id BIGINT NOT NULL DEFAULT 0,
    last_synced_timestamp TIMESTAMP WITH TIME ZONE DEFAULT '1970-01-01 00:00:00+00',
    total_records_synced BIGINT NOT NULL DEFAULT 0,
    last_sync_duration_ms NUMERIC(10, 2) DEFAULT 0.0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Operational OLTP Indexes
CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_updated_at ON orders(updated_at);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items(product_id);

-- Initialize pipeline checkpoint tracker
INSERT INTO sync_checkpoint (pipeline_name, last_synced_order_id, last_synced_timestamp, total_records_synced)
VALUES ('ecommerce_clickhouse_elt', 0, '1970-01-01 00:00:00+00', 0)
ON CONFLICT (pipeline_name) DO NOTHING;

-- Seed Initial Products
INSERT INTO products (name, category, price, cost, stock_quantity) VALUES
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
ON CONFLICT DO NOTHING;

-- Seed Initial Customers
INSERT INTO customers (name, email, segment, country) VALUES
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
ON CONFLICT (email) DO NOTHING;
