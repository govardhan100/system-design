# PostgreSQL Connection Pool Demo

A small Docker Compose example showing how `psycopg_pool.ConnectionPool` reuses bounded PostgreSQL connections in a FastAPI service. The demo seeds `mydb.users`, exposes a read-only `GET /users` query, and displays live pool statistics in a same-origin browser console.

Open [architecture.html](architecture.html) for the system diagram and connection lifecycle. Start the interactive console at `http://localhost:8003/demo`.

## Start

Requirements: Docker Desktop with Docker Compose. From this directory, configure a local password:

```sh
cp .env.example .env
```

Set `POSTGRES_PASSWORD` in `.env` to a URL-safe value, for example the output of `openssl rand -hex 24`. The supplied `DB_POOL_PORT` and `APP_PORT` defaults avoid common development ports; both host ports bind to `127.0.0.1` only.

```sh
docker compose up --build
```

Compose starts PostgreSQL, waits for its health check, then starts the API. PostgreSQL's initialization script creates `users` and inserts six sample rows. Database data persists in the `postgres-data` volume. The API uses the private backend network; host tools can connect to PostgreSQL through `localhost:5433`.

Open `http://localhost:8003/demo` to query users and watch pool metrics. The API is also available directly:

```sh
curl http://localhost:8003/users
curl http://localhost:8003/pool/stats
curl http://localhost:8003/readyz
```

Press **Run 12 concurrent reads** in the UI to issue parallel `/users` calls and observe pool availability, size, and waiting requests. `GET /pool/stats` exposes `ConnectionPool.get_stats()`.

To inspect the same local database with `psql`, load your `.env` and connect through the loopback-published port:

```sh
set -a
. ./.env
set +a
PGPASSWORD="$POSTGRES_PASSWORD" psql "host=localhost port=$DB_POOL_PORT dbname=mydb user=postgres" \
    -c 'SELECT id, name FROM users ORDER BY id'
```

## The pooling pattern

```python
from psycopg_pool import ConnectionPool

pool = ConnectionPool(
    conninfo="postgresql://postgres:password@db:5432/mydb",
    min_size=2,
    max_size=10,
    open=True,
)

def get_users():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM users ORDER BY id")
            return cur.fetchall()
```

The service configures the pool in its FastAPI lifespan, waits for startup, and closes it on shutdown. Synchronous route handlers run in FastAPI's worker threadpool. The connection context returns its lease to the pool after each query; it does not close the underlying pooled connection. If the pool is fully occupied and the acquisition timeout expires, the API returns `503`.

`min_size` and `max_size` apply to each API process. For `N` replicas, budget up to `N × max_size` PostgreSQL connections in addition to migrations, admin sessions, and other services.

## Tests

Run API tests in the container:

```sh
docker compose --profile test run --build --rm tests
```

The tests verify that `/users` executes through a borrowed/returned connection, pool stats and readiness are exposed, and the demo page is served as HTML.

Stop the app and database with `docker compose down`. This retains the named data volume.