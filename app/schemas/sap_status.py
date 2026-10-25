"""Safe, secret-free contracts for SAP Service Layer status verification."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.common import APIModel


class SAPStatusRead(APIModel):
    enabled: bool
    configured: bool
    service_layer_url_configured: bool
    company_db_configured: bool
    credentials_configured: bool
    verify_ssl: bool
    # Configuration alone must never be reported as live connection proof.
    live_connection_verified: bool = False
    supported_entities: list[str]


SAPVerificationState = Literal[
    "disabled",
    "not_configured",
    "configuration_invalid",
    "connection_unreachable",
    "authentication_failed",
    "authenticated_and_reachable",
    "read_only_verification_failed",
    "read_only_verification_passed",
]


class SAPVerificationRead(APIModel):
    state: SAPVerificationState
    message: str
    checked_at: datetime
    verified_at: datetime | None = None
    probe_resource: str = "BusinessPartners"
    records_returned: int | None = None
    error_category: str | None = None
    correlation_id: str
