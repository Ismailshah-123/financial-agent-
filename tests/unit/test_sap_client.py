"""
Unit tests for app.integrations.sap.client.SAPServiceLayerClient, using
httpx.MockTransport (built into httpx — no extra test dependency) to
simulate a Service Layer instance. These verify the client's OWN logic
(session handling, retry-on-401, error parsing) is correct; they do not
and cannot prove the client works against a real SAP Service Layer
deployment — see the client module's docstring for that caveat.

Every handler below also answers `/Logout` with 200, since
`client.close()` (called at the end of each test) logs out if a session
was established — without that, tests that successfully logged in
would fail during their own cleanup.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.sap.client import SAPServiceLayerClient
from app.integrations.sap.exceptions import (
    SAPAuthenticationError,
    SAPRequestError,
    SAPSessionExpiredError,
)


def _client_kwargs(transport: httpx.MockTransport) -> dict:
    return dict(
        base_url="https://sap.example.com:50000/b1s/v1",
        company_db="TESTDB",
        username="tester",
        password="secret",
        transport=transport,
    )


async def test_login_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Logout"):
            return httpx.Response(200)
        assert request.url.path.endswith("/Login")
        body = json.loads(request.content)
        assert body == {"CompanyDB": "TESTDB", "UserName": "tester", "Password": "secret"}
        return httpx.Response(
            200,
            json={"SessionId": "abc123"},
            headers={"Set-Cookie": "B1SESSION=abc123; Path=/"},
        )

    client = SAPServiceLayerClient(**_client_kwargs(httpx.MockTransport(handler)))
    await client.login()  # should not raise
    await client.close()


async def test_login_without_session_cookie_raises_authentication_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/Login")
        return httpx.Response(200, json={"SessionId": "abc123"})

    client = SAPServiceLayerClient(**_client_kwargs(httpx.MockTransport(handler)))
    with pytest.raises(SAPAuthenticationError, match="no B1SESSION cookie"):
        await client.login()
    await client.close()


async def test_login_failure_raises_authentication_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Logout"):
            return httpx.Response(200)
        return httpx.Response(401, json={"error": {"code": -304, "message": {"value": "bad creds"}}})

    client = SAPServiceLayerClient(**_client_kwargs(httpx.MockTransport(handler)))
    with pytest.raises(SAPAuthenticationError):
        await client.login()
    await client.close()  # never logged in — should be a no-op, not send /Logout


async def test_get_after_login_returns_parsed_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Login"):
            return httpx.Response(
            200,
            json={"SessionId": "abc123"},
            headers={"Set-Cookie": "B1SESSION=abc123; Path=/"},
        )
        if request.url.path.endswith("/Logout"):
            return httpx.Response(200)
        assert "BusinessPartners" in request.url.path
        return httpx.Response(200, json={"CardCode": "V0001", "CardName": "Acme Supplies"})

    client = SAPServiceLayerClient(**_client_kwargs(httpx.MockTransport(handler)))
    result = await client.get("BusinessPartners", "V0001")
    assert result["CardName"] == "Acme Supplies"
    await client.close()


async def test_error_response_is_parsed_into_sap_request_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Login"):
            return httpx.Response(
            200,
            json={"SessionId": "abc123"},
            headers={"Set-Cookie": "B1SESSION=abc123; Path=/"},
        )
        if request.url.path.endswith("/Logout"):
            return httpx.Response(200)
        return httpx.Response(
            400,
            json={"error": {"code": -5002, "message": {"value": "Invalid CardCode", "lang": "en"}}},
        )

    client = SAPServiceLayerClient(**_client_kwargs(httpx.MockTransport(handler)))
    with pytest.raises(SAPRequestError) as exc_info:
        await client.post("BusinessPartners", {"CardCode": "bad"})
    assert exc_info.value.sap_error_code == -5002
    assert exc_info.value.sap_error_message == "Invalid CardCode"
    await client.close()


async def test_expired_session_triggers_one_relogin_and_retry() -> None:
    login_calls = {"count": 0}
    get_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Login"):
            login_calls["count"] += 1
            return httpx.Response(
                200,
                json={"SessionId": f"session-{login_calls['count']}"},
                headers={"Set-Cookie": f"B1SESSION=session-{login_calls['count']}; Path=/"},
            )
        if request.url.path.endswith("/Logout"):
            return httpx.Response(200)
        if "BusinessPartners" in request.url.path:
            get_calls["count"] += 1
            if get_calls["count"] == 1:
                return httpx.Response(
                    401, json={"error": {"code": -1, "message": {"value": "expired"}}}
                )
            return httpx.Response(200, json={"CardCode": "V0001", "CardName": "Acme Supplies"})
        return httpx.Response(404)

    client = SAPServiceLayerClient(**_client_kwargs(httpx.MockTransport(handler)))
    result = await client.get("BusinessPartners", "V0001")
    assert result["CardName"] == "Acme Supplies"
    assert login_calls["count"] == 2  # initial login + one re-login after 401
    assert get_calls["count"] == 2  # failed attempt + successful retry
    await client.close()


async def test_persistent_401_raises_session_expired_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Login"):
            return httpx.Response(
            200,
            json={"SessionId": "abc123"},
            headers={"Set-Cookie": "B1SESSION=abc123; Path=/"},
        )
        if request.url.path.endswith("/Logout"):
            return httpx.Response(200)
        return httpx.Response(
            401, json={"error": {"code": -1, "message": {"value": "still expired"}}}
        )

    client = SAPServiceLayerClient(**_client_kwargs(httpx.MockTransport(handler)))
    with pytest.raises(SAPSessionExpiredError):
        await client.get("BusinessPartners", "V0001")
    await client.close()


async def test_patch_returns_none_on_204() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Login"):
            return httpx.Response(
            200,
            json={"SessionId": "abc123"},
            headers={"Set-Cookie": "B1SESSION=abc123; Path=/"},
        )
        if request.url.path.endswith("/Logout"):
            return httpx.Response(200)
        assert request.method == "PATCH"
        return httpx.Response(204)

    client = SAPServiceLayerClient(**_client_kwargs(httpx.MockTransport(handler)))
    result = await client.patch("BusinessPartners", "V0001", {"EmailAddress": "new@acme.example"})
    assert result is None
    await client.close()


async def test_missing_configuration_raises_authentication_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — never called
        raise AssertionError("should not send any request without configuration")

    client = SAPServiceLayerClient(
        base_url="",
        company_db=None,
        username=None,
        password=None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SAPAuthenticationError):
        await client.login()
    await client.close()
