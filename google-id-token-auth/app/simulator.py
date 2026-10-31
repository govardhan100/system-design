import base64
import time
import uuid
from typing import Any, Dict, Optional, Tuple
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import jwt

# Generate in-memory RSA keypair for simulator testing
_private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048
)
_public_key = _private_key.public_key()

SIMULATOR_KID = "simulated-google-key-id-01"
DEFAULT_DEMO_CLIENT_ID = "demo-localhost-app.apps.googleusercontent.com"


def get_simulator_public_pem() -> bytes:
    """Returns PEM-encoded public key for simulator verification."""
    return _public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )


def generate_simulated_id_token(
    name: str = "Alex Morgan",
    email: str = "developer.alex@gmail.com",
    picture: Optional[str] = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=256&q=80",
    client_id: Optional[str] = None,
    expired: bool = False,
    sub_id: Optional[str] = None
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """
    Generates a realistic RS256-signed OpenID Connect ID Token
    mimicking Google's exact payload and structure.
    """
    effective_client_id = client_id or DEFAULT_DEMO_CLIENT_ID
    now = int(time.time())
    
    if expired:
        iat = now - 7200
        exp = now - 3600  # expired 1 hour ago
    else:
        iat = now
        exp = now + 3600  # valid for 1 hour

    sub = sub_id or f"1{int(uuid.uuid4().int % 90000000000000000000) + 10000000000000000000}"
    name_parts = name.split(" ")
    given_name = name_parts[0] if name_parts else name
    family_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    headers = {
        "alg": "RS256",
        "kid": SIMULATOR_KID,
        "typ": "JWT"
    }

    payload = {
        "iss": "https://accounts.google.com",
        "azp": effective_client_id,
        "aud": effective_client_id,
        "sub": sub,
        "email": email,
        "email_verified": True,
        "at_hash": "hkEfilterDemoHash9812",
        "name": name,
        "picture": picture,
        "given_name": given_name,
        "family_name": family_name,
        "locale": "en",
        "iat": iat,
        "exp": exp,
        "jti": str(uuid.uuid4())
    }

    private_pem = _private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    encoded_token = jwt.encode(
        payload,
        private_pem,
        algorithm="RS256",
        headers=headers
    )

    return encoded_token, headers, payload
