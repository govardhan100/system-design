from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class VerifyTokenRequest(BaseModel):
    id_token: str = Field(..., description="Google ID Token (JWT) string")
    client_id: Optional[str] = Field(
        None, description="Expected Google OAuth Client ID (optional override)"
    )


class GoogleUserIdentity(BaseModel):
    sub: str = Field(..., description="Unique immutable Google Subject ID")
    email: str = Field(..., description="User's email address")
    email_verified: bool = Field(True, description="Whether email has been verified by Google")
    name: Optional[str] = Field(None, description="Full display name")
    given_name: Optional[str] = Field(None, description="First name")
    family_name: Optional[str] = Field(None, description="Last name")
    picture: Optional[str] = Field(None, description="Profile picture avatar URL")
    locale: Optional[str] = Field(None, description="User locale preference")
    hd: Optional[str] = Field(None, description="Google Workspace hosted domain (if applicable)")


class TokenVerificationReport(BaseModel):
    signature_valid: bool = Field(..., description="Cryptographic signature verified against JWKS")
    issuer_valid: bool = Field(..., description="Issuer matches accounts.google.com")
    audience_valid: bool = Field(..., description="Audience matches application Client ID")
    expiry_valid: bool = Field(..., description="Token is not expired")
    algorithm: str = Field("RS256", description="Signature algorithm")
    key_id: Optional[str] = Field(None, description="JWKS Key ID (kid) used to sign")
    issuer: str = Field(..., description="Token issuer claim (iss)")
    audience: str = Field(..., description="Token audience claim (aud)")
    issued_at: int = Field(..., description="Issued at UNIX timestamp (iat)")
    expires_at: int = Field(..., description="Expiration UNIX timestamp (exp)")
    time_to_expiry_sec: int = Field(..., description="Remaining seconds until expiration")
    verification_method: str = Field(
        "google_auth_sdk_and_jwks",
        description="Method used: 'google_auth_sdk', 'cryptography_jwks', or 'simulator_rsa'"
    )


class VerifyTokenResponse(BaseModel):
    success: bool
    message: str
    user: Optional[GoogleUserIdentity] = None
    raw_claims: Dict[str, Any] = Field(default_factory=dict)
    header: Dict[str, Any] = Field(default_factory=dict)
    raw_token: Optional[str] = None
    verification_report: Optional[TokenVerificationReport] = None
    session_token: Optional[str] = None
    is_simulated: bool = False


class SimulateTokenRequest(BaseModel):
    name: Optional[str] = Field("Alex Morgan", description="Full name for mock user")
    email: Optional[str] = Field("developer.alex@gmail.com", description="Email for mock user")
    picture: Optional[str] = Field(
        "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=256&q=80",
        description="Avatar URL"
    )
    client_id: Optional[str] = Field(None, description="Client ID to bake into audience claim")
    expired: bool = Field(False, description="Whether to simulate an intentionally expired token")


class AppConfigResponse(BaseModel):
    google_client_id: Optional[str] = None
    has_client_id: bool = False
    demo_mode: bool = True
    google_jwks_url: str = "https://www.googleapis.com/oauth2/v3/certs"
    app_name: str = "Google ID Token Localhost Verifier"
