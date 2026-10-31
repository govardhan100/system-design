import os
from pathlib import Path
from typing import Any, Dict, Optional
import jwt
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    AppConfigResponse,
    SimulateTokenRequest,
    VerifyTokenRequest,
    VerifyTokenResponse,
)
from app.simulator import generate_simulated_id_token
from app.verifier import get_google_jwks, verify_google_id_token

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
ENV_PATH = BASE_DIR / ".env"

# Auto-load .env if present
if ENV_PATH.exists():
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# Environment
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "localhost-dev-secret-key-32-chars-long!")

app = FastAPI(
    title="Google ID Token Identity Demo",
    description="Interactive OpenID Connect Identity flow from Browser -> Google -> Localhost Application",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
async def serve_index():
    """Serves the interactive Google ID Token visualizer UI."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Static UI not found</h1>", status_code=404)
    return FileResponse(index_path)


@app.get("/architecture", response_class=FileResponse)
async def serve_architecture():
    """Serves the deep-dive architecture and security documentation."""
    arch_path = BASE_DIR / "architecture.html"
    if not arch_path.exists():
        return HTMLResponse("<h1>Architecture document not found</h1>", status_code=404)
    return FileResponse(arch_path)


@app.get("/healthz")
async def health_check():
    """Liveness probe."""
    return {"status": "ok", "service": "google-id-token-auth"}


@app.get("/api/config", response_model=AppConfigResponse)
async def get_config():
    """
    Returns application configuration for frontend Google Sign-In SDK.
    """
    return AppConfigResponse(
        google_client_id=GOOGLE_CLIENT_ID or None,
        has_client_id=bool(GOOGLE_CLIENT_ID),
        demo_mode=(not bool(GOOGLE_CLIENT_ID)),
        google_jwks_url="https://www.googleapis.com/oauth2/v3/certs",
        app_name="Google ID Token Localhost Application"
    )


@app.post("/api/auth/google-login", response_model=VerifyTokenResponse)
async def google_login(payload: VerifyTokenRequest):
    """
    Core Endpoint: 'Your Application (localhost)' receives the Google ID Token.
    1. Cryptographically verifies token against Google's public JWKS.
    2. Validates 'aud', 'iss', 'exp'.
    3. Extracts verified user identity.
    4. Creates a local session token and returns full identity report.
    """
    effective_client_id = payload.client_id or GOOGLE_CLIENT_ID or None
    token_str = payload.id_token.strip()
    result = verify_google_id_token(
        token_str=token_str,
        expected_client_id=effective_client_id,
        session_secret=SESSION_SECRET
    )
    result.raw_token = token_str
    return result


@app.post("/api/auth/simulate", response_model=VerifyTokenResponse)
async def simulate_google_login(req: SimulateTokenRequest):
    """
    Simulates Google Login & Token issuance:
    Generates a realistic RS256-signed Google ID Token using an in-memory RSA keypair,
    then executes the full localhost identity verification pipeline.
    """
    token_str, _, _ = generate_simulated_id_token(
        name=req.name or "Alex Morgan",
        email=req.email or "developer.alex@gmail.com",
        picture=req.picture,
        client_id=req.client_id or GOOGLE_CLIENT_ID or "demo-localhost-app.apps.googleusercontent.com",
        expired=req.expired
    )

    result = verify_google_id_token(
        token_str=token_str,
        expected_client_id=req.client_id or GOOGLE_CLIENT_ID or "demo-localhost-app.apps.googleusercontent.com",
        session_secret=SESSION_SECRET
    )
    result.is_simulated = True
    result.raw_token = token_str
    return result


@app.get("/api/me")
async def get_current_user(authorization: Optional[str] = Header(None)):
    """
    Protected localhost API endpoint.
    Demonstrates that once the Google ID Token is verified, the localhost application
    can recognize the user identity via its own session token.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Expected 'Bearer <session_token>'."
        )

    token = authorization.split("Bearer ")[1].strip()
    try:
        claims = jwt.decode(token, SESSION_SECRET, algorithms=["HS256"])
        return {
            "authenticated": True,
            "message": "Access granted to protected localhost resource!",
            "session": claims
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Localhost session has expired. Please re-authenticate."
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid session token: {exc}"
        )


@app.get("/api/jwks-info")
async def get_jwks_info():
    """
    Fetches and inspects Google's live rotating public keys from
    https://www.googleapis.com/oauth2/v3/certs.
    """
    try:
        keys_data = get_google_jwks()
        return {
            "endpoint": "https://www.googleapis.com/oauth2/v3/certs",
            "key_count": len(keys_data.get("keys", [])),
            "keys": [
                {
                    "kid": k.get("kid"),
                    "kty": k.get("kty"),
                    "alg": k.get("alg"),
                    "use": k.get("use"),
                    "n_sample": (k.get("n", "")[:30] + "...") if k.get("n") else None
                }
                for k in keys_data.get("keys", [])
            ]
        }
    except Exception as exc:
        return {"error": str(exc)}
