import time
from typing import Any, Dict, Optional, Tuple
import requests
import jwt
from jwt.algorithms import RSAAlgorithm
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.models import GoogleUserIdentity, TokenVerificationReport, VerifyTokenResponse
from app.simulator import SIMULATOR_KID, get_simulator_public_pem

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ALLOWED_ISSUERS = ["accounts.google.com", "https://accounts.google.com"]

# Fallback active Google public keys in case of transient DNS resolution errors
FALLBACK_GOOGLE_JWKS: Dict[str, Any] = {
    "keys": [
        {
            "kid": "943a3a5d7d919625a454e489b75c29adab57acba",
            "alg": "RS256",
            "e": "AQAB",
            "kty": "RSA",
            "use": "sig",
            "n": "pIpnzA2ezyEERJSxiqpLBmMeIqATH-V6iuBtKIibXEyYovujrx8niqTeO6RIyXT6uDUUv0V2kJ8V_iWYFxzXY1BqK9IfcAmjg0XUDoyTVkoyLsF0gj299LH-zw5vCvy8jmamFIZKAbKcQ5hpHvSittM1vl-6vVL-i2GxyGbMA9aY6Hq15NylS1t7ELTYfQimlnvxcb7_DM0cuS5U1SfbCZMCpKhh0nrSlYds240oxpCJOV2rBahs_Ea5c7tezS1nwVC9W_E-bR9TF6BHkC_fv-E8DcWfkI_6geaJzBhINNxBfjx-w1-WUp2Jz3YYFWEfeQjxMqu-Fg6cGxwk7V16uQ"
        }
    ]
}

# In-memory JWKS cache initialized with fallback: (timestamp, jwks_data)
_jwks_cache: Tuple[float, Dict[str, Any]] = (time.time(), FALLBACK_GOOGLE_JWKS)
CACHE_TTL_SECONDS = 3600  # 1 hour


def get_google_jwks() -> Dict[str, Any]:
    """Fetches and caches Google's public JSON Web Key Set (JWKS) with automatic retry and fallback."""
    global _jwks_cache
    now = time.time()
    last_fetched, cached_data = _jwks_cache

    if cached_data and cached_data.get("keys") and (now - last_fetched < CACHE_TTL_SECONDS):
        return cached_data

    # Attempt fetch with retries
    for attempt in range(3):
        try:
            response = requests.get(GOOGLE_CERTS_URL, timeout=4)
            response.raise_for_status()
            data = response.json()
            if data and "keys" in data:
                _jwks_cache = (now, data)
                return data
        except Exception:
            if attempt < 2:
                time.sleep(0.5)

    # If network or DNS failed, return cached data or fallback keys
    if cached_data and cached_data.get("keys"):
        return cached_data
    return FALLBACK_GOOGLE_JWKS


def inspect_unverified_token(token: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Decodes header and payload without verifying signature for debugging/visualization."""
    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        return header, payload
    except Exception as exc:
        raise ValueError(f"Malformed JWT token: {exc}") from exc


def verify_google_id_token(
    token_str: str,
    expected_client_id: Optional[str] = None,
    session_secret: str = "default-session-secret"
) -> VerifyTokenResponse:
    """
    Verifies a Google ID Token:
    1. Validates format & decodes header.
    2. Identifies whether it's a simulated token or genuine Google token.
    3. Fetches Google JWKS and verifies RS256 signature.
    4. Validates 'iss' (issuer), 'aud' (audience), and 'exp' (expiration).
    5. Extracts user identity and generates localhost application session token.
    """
    now = int(time.time())

    # Step 1: Decode header & unverified payload
    try:
        header, unverified_payload = inspect_unverified_token(token_str)
    except ValueError as e:
        return VerifyTokenResponse(
            success=False,
            message=str(e),
            raw_claims={},
            header={}
        )

    kid = header.get("kid")
    alg = header.get("alg", "RS256")
    iss = unverified_payload.get("iss", "")
    aud = unverified_payload.get("aud", "")
    exp = unverified_payload.get("exp", 0)
    iat = unverified_payload.get("iat", 0)

    # Check for Simulator Token
    is_simulated = (kid == SIMULATOR_KID)
    verification_method = "simulator_rsa" if is_simulated else "google_jwks_rs256"

    # Step 2: Signature Verification
    verified_payload: Dict[str, Any] = {}
    try:
        if is_simulated:
            # Verify with in-memory simulator public key
            public_pem = get_simulator_public_pem()
            # If audience check requested
            audience_to_check = expected_client_id if expected_client_id else aud
            verified_payload = jwt.decode(
                token_str,
                public_pem,
                algorithms=["RS256"],
                options={"verify_exp": False, "verify_iss": False, "verify_aud": False}
            )
        else:
            # Genuine Google ID Token
            # Attempt 1: Official Google SDK
            try:
                request = google_requests.Request()
                verified_payload = google_id_token.verify_oauth2_token(
                    token_str,
                    request,
                    audience=expected_client_id if expected_client_id else None
                )
                verification_method = "google_auth_sdk"
            except Exception:
                # Attempt 2: Direct JWKS RS256 verification
                jwks = get_google_jwks()
                matching_jwk = None
                for key in jwks.get("keys", []):
                    if key.get("kid") == kid:
                        matching_jwk = key
                        break

                if not matching_jwk:
                    return VerifyTokenResponse(
                        success=False,
                        message=f"Google JWKS key ID '{kid}' not found in active Google certs.",
                        raw_claims=unverified_payload,
                        header=header
                    )

                public_key = RSAAlgorithm.from_jwk(matching_jwk)
                verified_payload = jwt.decode(
                    token_str,
                    public_key,
                    algorithms=["RS256"],
                    options={"verify_exp": False, "verify_iss": False, "verify_aud": False}
                )
                verification_method = "google_jwks_rs256"

        # Explicit Issuer verification (accounts.google.com or https://accounts.google.com)
        token_iss = verified_payload.get("iss", "")
        if token_iss not in ALLOWED_ISSUERS:
            return VerifyTokenResponse(
                success=False,
                message=f"Invalid issuer: 'iss' ('{token_iss}') is not an official Google issuer.",
                raw_claims=verified_payload,
                header=header
            )

        # Explicit Audience verification
        token_aud = verified_payload.get("aud", "")
        if expected_client_id and token_aud != expected_client_id:
            return VerifyTokenResponse(
                success=False,
                message=f"Audience mismatch: Token 'aud' claim ('{token_aud}') does not match expected client ID ('{expected_client_id}').",
                raw_claims=verified_payload,
                header=header
            )

    except jwt.InvalidAudienceError:
        return VerifyTokenResponse(
            success=False,
            message=f"Audience mismatch: Token 'aud' claim ('{aud}') does not match expected client ID ('{expected_client_id}').",
            raw_claims=unverified_payload,
            header=header
        )
    except jwt.InvalidIssuerError:
        return VerifyTokenResponse(
            success=False,
            message=f"Invalid issuer: 'iss' ('{iss}') is not an official Google issuer.",
            raw_claims=unverified_payload,
            header=header
        )
    except Exception as exc:
        return VerifyTokenResponse(
            success=False,
            message=f"Signature cryptographic verification failed: {exc}",
            raw_claims=unverified_payload,
            header=header
        )

    # Step 3: Check Expiration
    expiry_valid = exp > now
    time_to_expiry_sec = exp - now
    if not expiry_valid:
        return VerifyTokenResponse(
            success=False,
            message=f"Token has expired! Expired at timestamp {exp} ({abs(time_to_expiry_sec)} seconds ago).",
            raw_claims=verified_payload,
            header=header,
            verification_report=TokenVerificationReport(
                signature_valid=True,
                issuer_valid=(iss in ALLOWED_ISSUERS),
                audience_valid=(expected_client_id is None or aud == expected_client_id),
                expiry_valid=False,
                algorithm=alg,
                key_id=kid,
                issuer=iss,
                audience=aud,
                issued_at=iat,
                expires_at=exp,
                time_to_expiry_sec=time_to_expiry_sec,
                verification_method=verification_method
            ),
            is_simulated=is_simulated
        )

    # Step 4: Extract Verified Identity
    user_identity = GoogleUserIdentity(
        sub=str(verified_payload.get("sub", "")),
        email=str(verified_payload.get("email", "")),
        email_verified=bool(verified_payload.get("email_verified", False)),
        name=verified_payload.get("name"),
        given_name=verified_payload.get("given_name"),
        family_name=verified_payload.get("family_name"),
        picture=verified_payload.get("picture"),
        locale=verified_payload.get("locale"),
        hd=verified_payload.get("hd")
    )

    report = TokenVerificationReport(
        signature_valid=True,
        issuer_valid=(iss in ALLOWED_ISSUERS),
        audience_valid=(expected_client_id is None or aud == expected_client_id),
        expiry_valid=True,
        algorithm=alg,
        key_id=kid,
        issuer=iss,
        audience=aud,
        issued_at=iat,
        expires_at=exp,
        time_to_expiry_sec=time_to_expiry_sec,
        verification_method=verification_method
    )

    # Step 5: Issue Localhost Session Token
    # Your Application creates an internal session token so future calls to localhost
    # don't need to re-verify the external Google token on every microsecond.
    session_payload = {
        "sub": user_identity.sub,
        "email": user_identity.email,
        "name": user_identity.name,
        "picture": user_identity.picture,
        "auth_provider": "google",
        "iat": now,
        "exp": now + 86400  # 24-hour localhost session
    }
    session_token = jwt.encode(session_payload, session_secret, algorithm="HS256")

    return VerifyTokenResponse(
        success=True,
        message="Google ID Token successfully verified! Identity extracted.",
        user=user_identity,
        raw_claims=verified_payload,
        header=header,
        verification_report=report,
        session_token=session_token,
        is_simulated=is_simulated
    )
