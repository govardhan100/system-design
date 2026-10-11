from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from psycopg import OperationalError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout


def create_app(pool: ConnectionPool | None = None) -> FastAPI:
    owns_pool = pool is None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        active_pool = pool
        if active_pool is None:
            active_pool = ConnectionPool(
                conninfo=os.environ.get(
                    "DATABASE_URL",
                    "postgresql://postgres:postgres@localhost:5432/mydb",
                ),
                min_size=int(os.environ.get("POOL_MIN_SIZE", "2")),
                max_size=int(os.environ.get("POOL_MAX_SIZE", "10")),
                timeout=float(os.environ.get("POOL_WAIT_TIMEOUT", "2")),
                kwargs={"row_factory": dict_row},
                name="users-pool",
                open=False,
            )
            active_pool.open(wait=True, timeout=15)

        application.state.pool = active_pool
        try:
            yield
        finally:
            if owns_pool:
                active_pool.close()

    application = FastAPI(title="Psycopg Connection Pool Demo", lifespan=lifespan)

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    @application.get("/demo", response_class=HTMLResponse, include_in_schema=False)
    def demo() -> HTMLResponse:
        page = Path(__file__).with_name("demo.html").read_text(encoding="utf-8")
        return HTMLResponse(page)

    @application.get("/architecture.html", response_class=HTMLResponse, include_in_schema=False)
    def architecture() -> HTMLResponse:
        page = Path(__file__).with_name("architecture.html").read_text(encoding="utf-8")
        return HTMLResponse(page)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    def readyz(request: Request) -> dict[str, str]:
        try:
            with request.app.state.pool.connection() as connection:
                connection.execute("SELECT 1").fetchone()
        except (OperationalError, PoolTimeout):
            raise HTTPException(status_code=503, detail="Database pool unavailable") from None
        return {"status": "ready"}

    @application.get("/users")
    def get_users(request: Request) -> list[dict[str, int | str]]:
        try:
            with request.app.state.pool.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT id, name FROM users ORDER BY id")
                    return cursor.fetchall()
        except PoolTimeout:
            raise HTTPException(status_code=503, detail="Connection pool is busy") from None
        except OperationalError:
            raise HTTPException(status_code=503, detail="Database unavailable") from None

    @application.get("/pool/stats")
    def pool_stats(request: Request) -> dict[str, int | float]:
        return request.app.state.pool.get_stats()

    return application


app = create_app()