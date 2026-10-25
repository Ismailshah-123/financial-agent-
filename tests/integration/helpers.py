"""
tests.integration.helpers
============================
Small helpers shared across integration test modules — kept out of
`conftest.py` since these are plain async functions parameterized per
call (role, email), not fixtures.
"""

from __future__ import annotations

from httpx import AsyncClient


async def register_and_login(
    client: AsyncClient, *, unique_suffix: str, role: str = "finance_director"
) -> str:
    """Registers a fresh user with a globally-unique email and logs in,
    returning a bearer access token ready to use in an Authorization
    header. Asserts along the way so a setup failure fails loudly at the
    point it happened, not as a confusing downstream 401 in the actual
    test body."""
    email = f"test.{unique_suffix}@example.com"
    password = "TestPassword123!"

    register_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Test User {unique_suffix}",
            "role": role,
        },
    )
    assert register_response.status_code == 201, register_response.text

    login_response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200, login_response.text
    return login_response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
