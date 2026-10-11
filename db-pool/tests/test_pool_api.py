from contextlib import contextmanager

from fastapi.testclient import TestClient

from app import create_app


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query):
        self.query = query

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.cursor_instance = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        self.cursor_instance = FakeCursor(self.rows)
        return self.cursor_instance

    def execute(self, query):
        self.query = query
        return self

    def fetchone(self):
        return (1,)


class FakePool:
    def __init__(self):
        self.rows = [{"id": 1, "name": "Ada Lovelace"}]
        self.connection_count = 0
        self.connection_instance = None

    @contextmanager
    def connection(self):
        self.connection_count += 1
        self.connection_instance = FakeConnection(self.rows)
        try:
            yield self.connection_instance
        finally:
            self.connection_count -= 1

    def get_stats(self):
        return {"pool_size": 2, "pool_available": 2, "requests_waiting": 0}


def test_users_borrow_and_return_a_connection() -> None:
    pool = FakePool()
    with TestClient(create_app(pool=pool)) as client:
        response = client.get("/users")

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "name": "Ada Lovelace"}]
    assert pool.connection_count == 0
    assert pool.connection_instance.cursor_instance.query == "SELECT id, name FROM users ORDER BY id"


def test_ready_and_pool_stats_endpoints() -> None:
    with TestClient(create_app(pool=FakePool())) as client:
        ready = client.get("/readyz")
        stats = client.get("/pool/stats")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert stats.json()["pool_size"] == 2
    assert stats.json()["requests_waiting"] == 0


def test_demo_is_served_as_html() -> None:
    with TestClient(create_app(pool=FakePool())) as client:
        response = client.get("/demo")
        architecture = client.get("/architecture.html")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Connection Pool Lab" in response.text
    assert architecture.status_code == 200
    assert "text/html" in architecture.headers["content-type"]
    assert "PostgreSQL Connection Pool" in architecture.text