"""Mocked SAP read-only verification tests; require declared tenacity dependency."""
from __future__ import annotations
from datetime import datetime
from types import SimpleNamespace
import httpx
import pytest
pytest.importorskip("tenacity")
from starlette.requests import Request
from app.api.v1 import sap as sap_module
from app.integrations.sap.exceptions import SAPAuthenticationError, SAPRequestError

class _Secret:
    def __init__(self,value): self.value=value
    def get_secret_value(self): return self.value

def _config(enabled=True,complete=True,verify_ssl=True):
    return SimpleNamespace(enabled=enabled,service_layer_url="https://sap.example.test:50000/b1s/v1" if complete else None,
        company_db="TESTDB" if complete else None,username="test-user" if complete else None,
        password=_Secret("test-secret") if complete else None,verify_ssl=verify_ssl)

def _request():
    return Request({"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"POST",
        "scheme":"http","path":"/sap/verify","raw_path":b"/sap/verify","query_string":b"","headers":[],
        "client":("test-client",1234),"server":("test-server",80),"state":{"correlation_id":"corr-sap-test"},"root_path":""})

@pytest.mark.asyncio
async def test_disabled_sap_does_not_attempt_network(monkeypatch):
    monkeypatch.setattr(sap_module,"settings",SimpleNamespace(sap=_config(enabled=False)))
    monkeypatch.setattr(sap_module,"SAPServiceLayerClient",lambda **kwargs: (_ for _ in ()).throw(AssertionError("network client should not be constructed")))
    result=await sap_module.verify_sap_read_only(_request(),actor=None)
    assert result.state=="disabled" and result.verified_at is None and result.correlation_id=="corr-sap-test"

@pytest.mark.asyncio
async def test_missing_incomplete_or_insecure_tls_configuration(monkeypatch):
    monkeypatch.setattr(sap_module,"settings",SimpleNamespace(sap=_config(complete=False)))
    result=await sap_module.verify_sap_read_only(_request(),actor=None)
    assert result.state=="not_configured"
    cfg=_config();cfg.password=None
    monkeypatch.setattr(sap_module,"settings",SimpleNamespace(sap=cfg))
    result=await sap_module.verify_sap_read_only(_request(),actor=None)
    assert result.state=="configuration_invalid"
    monkeypatch.setattr(sap_module,"settings",SimpleNamespace(sap=_config(verify_ssl=False)))
    monkeypatch.setattr(sap_module,"SAPServiceLayerClient",lambda **kwargs: (_ for _ in ()).throw(AssertionError("TLS off must be refused")))
    result=await sap_module.verify_sap_read_only(_request(),actor=None)
    assert result.error_category=="tls_verification_disabled"

@pytest.mark.asyncio
async def test_success_only_after_login_and_read_only_probe(monkeypatch):
    monkeypatch.setattr(sap_module,"settings",SimpleNamespace(sap=_config()))
    class FakeClient:
        def __init__(self,**kwargs): assert kwargs["verify_ssl"] is True and kwargs["request_timeout_seconds"]==10.0
        async def login(self): return None
        async def get(self,resource,*,params=None):
            assert resource=="BusinessPartners" and params=={"$top":1,"$select":"CardCode,CardName,CardType"}
            return {"value":[{"CardCode":"C001"}]}
        async def close(self): return None
    monkeypatch.setattr(sap_module,"SAPServiceLayerClient",FakeClient)
    result=await sap_module.verify_sap_read_only(_request(),actor=None)
    assert result.state=="read_only_verification_passed" and result.records_returned==1
    assert result.verified_at is not None and isinstance(result.checked_at,datetime)

@pytest.mark.asyncio
async def test_auth_failure_and_network_failure_are_normalized(monkeypatch):
    monkeypatch.setattr(sap_module,"settings",SimpleNamespace(sap=_config()))
    class AuthClient:
        def __init__(self,**kwargs): pass
        async def login(self): raise SAPAuthenticationError("private credentials detail")
        async def close(self): return None
    monkeypatch.setattr(sap_module,"SAPServiceLayerClient",AuthClient)
    result=await sap_module.verify_sap_read_only(_request(),actor=None)
    assert result.state=="authentication_failed" and "private credentials" not in result.message
    class NetworkClient:
        def __init__(self,**kwargs): pass
        async def login(self): raise httpx.ConnectError("internal network detail",request=httpx.Request("POST","https://sap.example.test/Login"))
        async def close(self): return None
    monkeypatch.setattr(sap_module,"SAPServiceLayerClient",NetworkClient)
    result=await sap_module.verify_sap_read_only(_request(),actor=None)
    assert result.state=="connection_unreachable" and "internal network detail" not in result.message

@pytest.mark.asyncio
async def test_rejected_read_does_not_claim_verification_passed(monkeypatch):
    monkeypatch.setattr(sap_module,"settings",SimpleNamespace(sap=_config()))
    class FakeClient:
        def __init__(self,**kwargs): pass
        async def login(self): return None
        async def get(self,resource,*,params=None): raise SAPRequestError("rejected",status_code=403,resource=resource)
        async def close(self): return None
    monkeypatch.setattr(sap_module,"SAPServiceLayerClient",FakeClient)
    result=await sap_module.verify_sap_read_only(_request(),actor=None)
    assert result.state=="authenticated_and_reachable" and result.error_category=="read_rejected" and result.verified_at is None
