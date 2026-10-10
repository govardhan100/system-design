from datetime import UTC, datetime, timedelta
from hashlib import sha256
import secrets
from uuid import uuid4

import jwt
from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()


class InvalidAccessToken(Exception):
    pass


class TokenManager:
    def __init__(
        self,
        secret: str,
        issuer: str = "auth-service",
        audience: str = "system-design-api",
        access_ttl_seconds: int = 900,
        refresh_ttl_seconds: int = 60 * 60 * 24 * 14,
    ) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("AUTH_JWT_SECRET must contain at least 32 bytes")
        self._secret = secret
        self.issuer = issuer
        self.audience = audience
        self.access_ttl_seconds = access_ttl_seconds
        self.refresh_ttl_seconds = refresh_ttl_seconds

    def create_access_token(self, user_id: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": user_id,
                "iss": self.issuer,
                "aud": self.audience,
                "iat": now,
                "exp": now + timedelta(seconds=self.access_ttl_seconds),
                "jti": str(uuid4()),
                "typ": "access",
            },
            self._secret,
            algorithm="HS256",
        )

    def decode_access_token(self, token: str) -> str:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["sub", "iss", "aud", "iat", "exp", "jti", "typ"]},
            )
        except jwt.PyJWTError as error:
            raise InvalidAccessToken from error
        subject = claims.get("sub")
        if claims.get("typ") != "access" or not isinstance(subject, str) or not subject:
            raise InvalidAccessToken
        return subject

    @staticmethod
    def create_refresh_token() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def hash_refresh_token(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()

    def refresh_expiry(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.refresh_ttl_seconds)