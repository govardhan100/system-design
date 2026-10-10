from contextlib import asynccontextmanager
from datetime import UTC, datetime
import os
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from auth_service.database import get_session
from auth_service.models import RefreshToken, Role, User
from auth_service.schemas import Credentials, PrincipalResponse, RefreshRequest, TokenResponse
from auth_service.security import InvalidAccessToken, TokenManager, password_hash


SERVICE_ROOT = Path(__file__).resolve().parent.parent


def create_app(
    database_url: str | None = None,
    jwt_secret: str | None = None,
    issuer: str | None = None,
    audience: str | None = None,
) -> FastAPI:
    resolved_database_url = database_url or os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://auth:auth@localhost:5432/auth"
    )
    resolved_secret = jwt_secret or os.getenv(
        "AUTH_JWT_SECRET", "local-development-key-not-for-production-000000000000"
    )
    engine = create_async_engine(resolved_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token_manager = TokenManager(
        resolved_secret,
        issuer=issuer or os.getenv("AUTH_JWT_ISSUER", "auth-service"),
        audience=audience or os.getenv("AUTH_JWT_AUDIENCE", "system-design-api"),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await engine.dispose()

    app = FastAPI(title="Authentication Service", lifespan=lifespan)
    app.state.session_factory = session_factory

    @app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
    async def demo() -> HTMLResponse:
        return HTMLResponse((Path(__file__).parent / "demo.html").read_text(encoding="utf-8"))

    @app.get("/auth/architecture", response_class=HTMLResponse, include_in_schema=False)
    async def architecture() -> HTMLResponse:
        return HTMLResponse((SERVICE_ROOT / "architecture.html").read_text(encoding="utf-8"))

    @app.get("/auth/TEST_REPORT.md", response_class=PlainTextResponse, include_in_schema=False)
    async def test_report() -> PlainTextResponse:
        return PlainTextResponse((SERVICE_ROOT / "TEST_REPORT.md").read_text(encoding="utf-8"))

    def refresh_expired(expires_at: datetime, now: datetime) -> bool:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= now

    async def current_user(
        authorization: str | None = Header(default=None),
        session=Depends(get_session),
    ) -> User:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Bearer token required")
        try:
            user_id = token_manager.decode_access_token(authorization[7:].strip())
        except InvalidAccessToken:
            raise HTTPException(status_code=401, detail="Invalid access token") from None
        user = await session.scalar(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.id == user_id)
        )
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid access token")
        return user

    def require_permission(permission_name: str):
        async def check_permission(user: User = Depends(current_user)) -> User:
            permissions = {
                permission.name
                for role in user.roles
                for permission in role.permissions
            }
            if permission_name not in permissions:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return user

        return check_permission

    async def issue_tokens(session, user: User, family_id: str | None = None) -> TokenResponse:
        refresh_value = token_manager.create_refresh_token()
        session.add(
            RefreshToken(
                id=str(uuid4()),
                token_hash=token_manager.hash_refresh_token(refresh_value),
                family_id=family_id or str(uuid4()),
                user_id=user.id,
                expires_at=token_manager.refresh_expiry(),
                revoked_at=None,
                created_at=datetime.now(UTC),
            )
        )
        return TokenResponse(
            access_token=token_manager.create_access_token(user.id),
            refresh_token=refresh_value,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(session=Depends(get_session)) -> dict[str, str]:
        try:
            await session.execute(select(func.now()))
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail="Database unavailable") from None
        return {"status": "ready"}

    @app.post("/auth/signup", response_model=TokenResponse, status_code=201)
    async def signup(payload: Credentials, session=Depends(get_session)) -> TokenResponse:
        existing = await session.scalar(select(User.id).where(User.email == payload.email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Account already exists")
        role = await session.scalar(select(Role).where(Role.name == "user"))
        if role is None:
            raise HTTPException(status_code=503, detail="Auth roles are not initialized")
        user = User(
            id=str(uuid4()),
            email=payload.email,
            password_hash=password_hash.hash(payload.password),
            is_active=True,
            rate_limit_tier="basic",
            created_at=datetime.now(UTC),
            roles=[role],
        )
        session.add(user)
        tokens = await issue_tokens(session, user)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Account already exists") from None
        return tokens

    @app.post("/auth/login", response_model=TokenResponse)
    async def login(payload: Credentials, session=Depends(get_session)) -> TokenResponse:
        user = await session.scalar(
            select(User).options(selectinload(User.roles)).where(User.email == payload.email)
        )
        if (
            user is None
            or not user.is_active
            or not password_hash.verify(payload.password, user.password_hash)
        ):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        tokens = await issue_tokens(session, user)
        await session.commit()
        return tokens

    @app.post("/auth/refresh", response_model=TokenResponse)
    async def refresh(payload: RefreshRequest, session=Depends(get_session)) -> TokenResponse:
        stored = await session.scalar(
            select(RefreshToken)
            .where(
                RefreshToken.token_hash
                == token_manager.hash_refresh_token(payload.refresh_token)
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        if stored is None:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        if stored.revoked_at is not None:
            await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == stored.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.commit()
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        if refresh_expired(stored.expires_at, now):
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        user = await session.scalar(
            select(User).options(selectinload(User.roles)).where(User.id == stored.user_id)
        )
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        stored.revoked_at = now
        tokens = await issue_tokens(session, user, stored.family_id)
        await session.commit()
        return tokens

    @app.post("/auth/logout", status_code=204)
    async def logout(payload: RefreshRequest, session=Depends(get_session)) -> Response:
        stored = await session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash
                == token_manager.hash_refresh_token(payload.refresh_token)
            )
        )
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            await session.commit()
        return Response(status_code=204)

    @app.get("/auth/me", response_model=PrincipalResponse)
    async def me(user: User = Depends(current_user)) -> PrincipalResponse:
        return PrincipalResponse(
            subject=user.id,
            email=user.email,
            roles=sorted(role.name for role in user.roles),
            permissions=sorted(
                permission.name
                for role in user.roles
                for permission in role.permissions
            ),
            rate_limit_tier=user.rate_limit_tier,
        )

    @app.get("/auth/admin/users")
    async def list_users(
        _: User = Depends(require_permission("users:read")),
        session=Depends(get_session),
    ) -> list[dict[str, str]]:
        users = (await session.scalars(select(User).order_by(User.created_at))).all()
        return [{"id": user.id, "email": user.email} for user in users]

    @app.api_route("/verify", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def verify(user: User = Depends(current_user)) -> Response:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={
                "X-Auth-Subject": user.id,
                "X-Auth-Roles": ",".join(sorted(role.name for role in user.roles)),
                "X-Auth-Tier": user.rate_limit_tier,
            },
        )

    return app


app = create_app()