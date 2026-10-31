import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.simulator import generate_simulated_id_token
from app.verifier import verify_google_id_token

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_config_endpoint():
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "demo_mode" in data
    assert "google_jwks_url" in data


def test_simulate_token_endpoint():
    payload = {
        "name": "Sarah Connor",
        "email": "sarah.connor@cyberdyne.demo",
        "picture": "https://example.com/avatar.jpg"
    }
    response = client.post("/api/auth/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["user"]["name"] == "Sarah Connor"
    assert data["user"]["email"] == "sarah.connor@cyberdyne.demo"
    assert data["user"]["sub"].startswith("1")
    assert data["session_token"] is not None
    assert data["verification_report"]["signature_valid"] is True
    assert data["verification_report"]["expiry_valid"] is True


def test_verify_token_direct():
    token_str, _, _ = generate_simulated_id_token(
        name="John Doe",
        email="john.doe@gmail.com",
        client_id="my-test-client.apps.googleusercontent.com"
    )
    res = verify_google_id_token(
        token_str,
        expected_client_id="my-test-client.apps.googleusercontent.com"
    )
    assert res.success is True
    assert res.user.email == "john.doe@gmail.com"
    assert res.user.name == "John Doe"
    assert res.verification_report.audience_valid is True


def test_audience_mismatch_rejected():
    token_str, _, _ = generate_simulated_id_token(
        name="Intruder",
        email="intruder@example.com",
        client_id="legitimate-app-1.apps.googleusercontent.com"
    )
    # Verification expects a different client ID
    res = verify_google_id_token(
        token_str,
        expected_client_id="different-app-2.apps.googleusercontent.com"
    )
    assert res.success is False
    assert "Audience mismatch" in res.message


def test_expired_token_rejected():
    token_str, _, _ = generate_simulated_id_token(
        name="Expired User",
        email="expired@example.com",
        expired=True
    )
    res = verify_google_id_token(token_str)
    assert res.success is False
    assert "expired" in res.message.lower()
    assert res.verification_report.expiry_valid is False


def test_malformed_token_rejected():
    res = verify_google_id_token("not-a-valid-jwt-token-string")
    assert res.success is False
    assert "Malformed JWT" in res.message


def test_protected_api_me_flow():
    # 1. Simulate authentication
    sim_resp = client.post("/api/auth/simulate", json={"name": "Alice Bob", "email": "alice@gmail.com"})
    assert sim_resp.status_code == 200
    session_token = sim_resp.json()["session_token"]
    assert session_token is not None

    # 2. Call /api/me with session token
    headers = {"Authorization": f"Bearer {session_token}"}
    me_resp = client.get("/api/me", headers=headers)
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["authenticated"] is True
    assert me_data["session"]["email"] == "alice@gmail.com"
    assert me_data["session"]["name"] == "Alice Bob"


def test_protected_api_me_unauthorized():
    # Calling without header
    resp = client.get("/api/me")
    assert resp.status_code == 401

    # Calling with invalid token
    resp_invalid = client.get("/api/me", headers={"Authorization": "Bearer invalid.token.value"})
    assert resp_invalid.status_code == 401
