import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auth_service.main import create_app
from auth_service.models import Base, Permission, Role
from auth_service.bootstrap_admin import promote_admin


@pytest.fixture
def client(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'auth-test.db'}"

    async def initialize_database() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            profile = Permission(id=str(uuid4()), name="profile:read")
            users = Permission(id=str(uuid4()), name="users:read")
            user_role = Role(id=str(uuid4()), name="user", permissions=[profile])
            admin_role = Role(
                id=str(uuid4()), name="admin", permissions=[profile, users]
            )
            session.add_all([user_role, admin_role])
            await session.commit()
        await engine.dispose()

    asyncio.run(initialize_database())
    application = create_app(
        database_url=database_url,
        jwt_secret="test-secret-that-is-at-least-32-bytes-long",
    )
    with TestClient(application) as test_client:
        yield test_client


def signup(client: TestClient, email: str = "person@example.com") -> dict[str, str]:
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "a-long-password-for-tests",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_demo_console_is_served_as_html(client) -> None:
    response = client.get("/demo")
    architecture = client.get("/auth/architecture")
    report = client.get("/auth/TEST_REPORT.md")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Identity Console" in response.text
    assert "Check admin access" in response.text
    assert "text/html" in architecture.headers["content-type"]
    assert "Authentication Service" in architecture.text
    assert "Authentication Service Test Report" in report.text


def test_signup_normalizes_email_and_never_accepts_requested_role(client) -> None:
    tokens = signup(client, " Person@Example.COM ")
    profile = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert profile.status_code == 200
    assert profile.json()["email"] == "person@example.com"
    assert profile.json()["roles"] == ["user"]
    assert profile.json()["permissions"] == ["profile:read"]
    assert profile.json()["rate_limit_tier"] == "basic"


def test_duplicate_signup_and_invalid_login_are_rejected(client) -> None:
    signup(client)
    duplicate = client.post(
        "/auth/signup",
        json={"email": "PERSON@example.com", "password": "a-long-password-for-tests"},
    )
    invalid_login = client.post(
        "/auth/login",
        json={"email": "person@example.com", "password": "wrong-password-123"},
    )

    assert duplicate.status_code == 409
    assert invalid_login.status_code == 401


def test_forward_auth_returns_verified_principal_and_tier(client) -> None:
    tokens = signup(client)
    no_token = client.post("/verify")
    verified = client.post(
        "/verify", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert no_token.status_code == 401
    assert verified.status_code == 204
    assert verified.headers["X-Auth-Subject"]
    assert verified.headers["X-Auth-Roles"] == "user"
    assert verified.headers["X-Auth-Tier"] == "basic"


def test_user_cannot_access_admin_endpoint(client) -> None:
    tokens = signup(client)
    response = client.get(
        "/auth/admin/users",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 403


def test_operator_promotion_grants_admin_permission(client, tmp_path, monkeypatch) -> None:
    tokens = signup(client)
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'auth-test.db'}"
    )
    asyncio.run(promote_admin("person@example.com"))
    response = client.get(
        "/auth/admin/users",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json() == [
        {"id": client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()["subject"],
         "email": "person@example.com"}
    ]


def test_refresh_rotates_and_revokes_previous_token(client) -> None:
    tokens = signup(client)
    rotated = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    reused = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    replayed_family = client.post(
        "/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
    )

    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != tokens["refresh_token"]
    assert reused.status_code == 401
    assert replayed_family.status_code == 401


def test_logout_revokes_refresh_token(client) -> None:
    tokens = signup(client)
    logout = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    refreshed = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert logout.status_code == 204
    assert refreshed.status_code == 401