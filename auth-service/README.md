# Authentication Service

FastAPI authentication and role-based authorization service for the protected API stack. It stores users, roles, permissions, and hashed refresh tokens in PostgreSQL; Traefik calls `/verify` before forwarding protected API traffic to the rate limiter.

See the [auth-service architecture and HTML test report](architecture.html), the [detailed Markdown test report](TEST_REPORT.md), and the [integrated solution architecture](../rate-limit/architecture.html). The [gateway README](../rate-limit/README.md) has end-to-end run instructions.

After starting the Compose stack, open the interactive demo console at `http://localhost:8080/demo`.

## Endpoints

| Method | Path | Access |
| --- | --- | --- |
| `POST` | `/auth/signup` | Public; new account receives only `user` role and `basic` tier |
| `POST` | `/auth/login` | Public; returns access and refresh tokens |
| `POST` | `/auth/refresh` | Public with a valid one-time refresh token |
| `POST` | `/auth/logout` | Public with the refresh token to revoke |
| `GET` | `/auth/me` | Bearer access token |
| `GET` | `/auth/admin/users` | Bearer token with `users:read` permission |
| `GET` or `POST` | `/verify` | Internal Traefik ForwardAuth contract |

The access JWT lifetime is 15 minutes. Refresh tokens are opaque, stored as SHA-256 hashes, rotate on use, and are revoked as a family if a rotated token is replayed. Passwords are hashed using Argon2id. JWT checks pin HS256 and validate issuer, audience, expiry, token type, and subject.

## Configuration

The integrated Compose file is `../rate-limit/compose.yaml`. Create `rate-limit/.env` from its example and set:

- `AUTH_JWT_SECRET`: at least 32 random bytes; use a managed secret store outside local development.
- `AUTH_DB_PASSWORD`: alphanumeric PostgreSQL password used by the auth service and database container.

The auth image waits for PostgreSQL, runs `alembic upgrade head`, then serves on its internal port. PostgreSQL is persistent and attached only to the internal `auth-backend` network. The auth service readiness endpoint checks its SQL connection; `/healthz` is liveness-only.

## Authorization operations

The initial migration seeds `user` and `admin` roles plus `profile:read` and `users:read` permissions. Public signup never accepts a role or tier field. Create an account first, then grant admin from the Compose project directory:

```sh
docker compose exec auth-service python -m auth_service.bootstrap_admin account@example.com
```

The command only promotes an existing account and is intended for an operator with container access. Rate-limit tiers are read from the user row by auth; callers cannot change them through API requests or identity headers.

## Tests

From `rate-limit/`, run the SQLite-backed auth API/security suite:

```sh
docker compose --profile test run --build --rm auth-tests
```

The tests cover normalized signup, duplicate accounts, role assignment, permission denial, ForwardAuth headers, invalid and expired JWTs, refresh rotation/replay, and logout revocation. The full integrated runtime also requires Docker Compose and its PostgreSQL/Redis services.