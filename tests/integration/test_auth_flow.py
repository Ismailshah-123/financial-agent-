"""
Integration tests for app.api.v1.auth — registration, login, and the
error paths (duplicate email, wrong password) — run against a real
Postgres database and the actual FastAPI app. See
tests/integration/conftest.py for setup requirements.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.helpers import auth_headers, register_and_login


async def test_register_then_login_succeeds(client: AsyncClient, unique_suffix: str) -> None:
    token = await register_and_login(client, unique_suffix=unique_suffix)
    assert token

    # The token should actually authorize a real request.
    response = await client.get("/api/v1/vendors", headers=auth_headers(token))
    assert response.status_code == 200


async def test_duplicate_email_registration_is_rejected(
    client: AsyncClient, unique_suffix: str
) -> None:
    email = f"dup.{unique_suffix}@example.com"
    payload = {
        "email": email,
        "password": "TestPassword123!",
        "full_name": "First User",
        "role": "viewer",
    }
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


async def test_login_with_wrong_password_is_rejected(
    client: AsyncClient, unique_suffix: str
) -> None:
    email = f"wrongpw.{unique_suffix}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "CorrectPassword123!",
            "full_name": "Wrong PW User",
            "role": "viewer",
        },
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "IncorrectPassword"}
    )
    assert response.status_code == 401


async def test_login_with_unknown_email_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "no-such-user@example.com", "password": "whatever123"},
    )
    assert response.status_code == 401


async def test_protected_endpoint_without_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vendors")
    assert response.status_code == 401


async def test_refresh_token_issues_new_access_token(
    client: AsyncClient, unique_suffix: str
) -> None:
    email = f"refresh.{unique_suffix}@example.com"
    password = "TestPassword123!"
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Refresh User",
            "role": "viewer",
        },
    )
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    refresh_token = login_response.json()["refresh_token"]

    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_response.status_code == 200
    refreshed = refresh_response.json()
    assert refreshed["access_token"]
    assert refreshed["refresh_token"] != refresh_token
    assert refreshed["expires_in"] > 0

    # Refresh-token rotation prevents replay of the previous refresh token.
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert replay.status_code == 401

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": refreshed["refresh_token"]})
    assert logout.status_code == 200
    revoked = await client.post("/api/v1/auth/refresh", json={"refresh_token": refreshed["refresh_token"]})
    assert revoked.status_code == 401
