"""
app.integrations.sap
=======================
SAP Business One Service Layer integration.

    client.py       — SAPServiceLayerClient: session-based HTTP client
                        (login/logout, generic get/post/patch/delete).
                        NOT verified against a real SAP instance — see
                        its module docstring for the honest caveat.
    exceptions.py     — SAPAuthenticationError, SAPRequestError,
                        SAPSessionExpiredError
    mappers.py         — pure functions mapping Vendor/Customer <-> SAP
                        BusinessPartner JSON, plus discrepancy detection

`app.services.sap_sync_service` and `app.agents.sap_integration` are
what actually use this package — nothing here talks to a repository or
knows about database sessions.
"""
