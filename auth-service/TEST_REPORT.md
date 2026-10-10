# Authentication Service Test Report

**Date:** 2026-10-10
**Result:** PASS
**Environment:** macOS, Docker Engine 28.5.1, Python 3.12 service containers

## Automated Tests

| Check | Result |
| --- | --- |
| Compose configuration validation | Passed |
| Auth API/security suite (`auth-tests`) | 11 passed |
| Redis-backed rate-limit suite (`tests`) | 10 passed |
| Initial PostgreSQL migration SQL generation | Passed; 85 SQL lines generated |
| Whitespace validation (`git diff --check`) | Passed |

The auth suite covered account creation and email normalization, role assignment, login, permission denial, operator admin promotion, ForwardAuth identity headers, JWT signature/issuer/audience/expiry checks, refresh rotation/replay, and logout revocation.

## Integrated Smoke Test

Started the full Compose stack with three application replicas and tested through Traefik:

- `/healthz` returned `200`.
- Missing and invalid bearer tokens were rejected with `401`.
- Signup returned `201`; a caller-supplied `role: admin` did not elevate the new account.
- The basic user received `403` from `/auth/admin/users`; operator promotion enabled access with `200`.
- Six requests with forged `X-Auth-Subject`, forged premium tier, and a forged body `user_id` yielded five `200` responses followed by `429`. Allowed responses returned the verified subject, demonstrating the client values did not change identity or tier.
- Login returned `200`; refresh rotation returned `200`; logout returned `204`; reuse of the revoked refresh token returned `401`.

## Notes

The first ad-hoc refresh probe omitted `Content-Type: application/json` and received `422` for the raw JSON body. With the correct content type, refresh passed both directly and in the complete smoke test; no service code change was required.

The auth test run emitted a non-failing Starlette deprecation warning about `httpx` in `TestClient`. No Docker-backed checks remain outstanding.

## Interactive Demo Console

The demo console is served at `http://localhost:8080/demo` by the auth service through Traefik.

- Browser opened the console successfully; gateway status displayed online.
- Desktop screenshot was inspected; at a 390px mobile viewport, document width remained 390px with no horizontal overflow.
- Browser signup displayed the authenticated account, `user` role, `basic` tier, and access-token countdown.
- The permission control returned `403` for a basic user, then `200` after operator promotion to admin.
- The six-request burst control showed five successful responses followed by `429`.
- Refresh rotated the token successfully; sign out revoked the refresh token and cleared the in-memory session.