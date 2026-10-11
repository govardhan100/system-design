CREATE TABLE IF NOT EXISTS users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL
);

INSERT INTO users (name) VALUES
    ('Ada Lovelace'),
    ('Grace Hopper'),
    ('Edsger Dijkstra'),
    ('Barbara Liskov'),
    ('Donald Knuth'),
    ('Margaret Hamilton')
ON CONFLICT DO NOTHING;