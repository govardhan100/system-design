import pytest

from auth_service.security import InvalidAccessToken, TokenManager


def test_access_token_checks_issuer_audience_and_signature() -> None:
    issuer = TokenManager("a" * 32, issuer="issuer-a", audience="api-a")
    assert issuer.decode_access_token(issuer.create_access_token("user-1")) == "user-1"

    wrong_audience = TokenManager("a" * 32, issuer="issuer-a", audience="api-b")
    with pytest.raises(InvalidAccessToken):
        wrong_audience.decode_access_token(issuer.create_access_token("user-1"))

    wrong_key = TokenManager("b" * 32, issuer="issuer-a", audience="api-a")
    with pytest.raises(InvalidAccessToken):
        wrong_key.decode_access_token(issuer.create_access_token("user-1"))


def test_refresh_token_storage_uses_one_way_hash() -> None:
    token = TokenManager.create_refresh_token()
    digest = TokenManager.hash_refresh_token(token)
    assert len(token) > 32
    assert digest != token
    assert TokenManager.hash_refresh_token(token) == digest


def test_signing_secret_must_be_at_least_32_bytes() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        TokenManager("short")


def test_expired_access_token_is_rejected() -> None:
    manager = TokenManager("a" * 32, access_ttl_seconds=-1)
    with pytest.raises(InvalidAccessToken):
        manager.decode_access_token(manager.create_access_token("user-1"))