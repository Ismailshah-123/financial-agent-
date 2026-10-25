# SAP Live Verification Checklist

Status on **2026-10-09**: **PENDING CONTROLLED SAP ENVIRONMENT**

No live SAP Business One credentials or reachable Service Layer environment were available during this repository hardening pass. Therefore no live SAP verification claim is made.

## Required controlled test environment

Use an approved SAP Business One sandbox/test company with test records and non-production credentials.

## Checklist

- [ ] Confirm Service Layer base URL and TLS certificate chain.
- [ ] Authenticate successfully.
- [ ] Confirm session handling and logout.
- [ ] Read a harmless master-data object.
- [ ] Read a customer and vendor.
- [ ] Validate internal → SAP customer mapping.
- [ ] Validate internal → SAP vendor mapping.
- [ ] Read a supported finance document.
- [ ] Run a controlled synchronization.
- [ ] Verify SAP response and internal persistence.
- [ ] Verify duplicate prevention after repeated source runs.
- [ ] Simulate a transport timeout against a safe test mutation and verify the client reports reconciliation required rather than replaying it.
- [ ] Simulate an expired SAP session during a mutation and verify replay is blocked.
- [ ] Verify SAP error-code normalization.
- [ ] Verify correlation/audit records are present.
- [ ] Verify a controlled write produces the expected SAP document and can be reconciled back to the internal record.

## Evidence standard

The result should identify exact SAP Business One version/build, target company database, date/time, operator/test account, test record identifiers, and screenshots/log references. A CI mock pass must never be recorded as live SAP verification.


## Current status of read-only probe (2026-10-10)

The SAP Integration page now exposes **Verify read-only connection**, calling `POST /api/v1/sap/verify`. This backend probe authenticates, reads at most one selected BusinessPartners record and returns its result state/correlation ID. It enforces certificate validation and never returns credentials/session cookies. It still has not been tested against an approved live SAP tenant. Live company version, endpoint, mapping semantics, sync/repeat behavior, reconciliation and any controlled writes remain `BLOCKED_EXTERNAL_SAP` until a test tenant/credentials are supplied through secure runtime configuration.
