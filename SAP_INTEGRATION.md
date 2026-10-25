# SAP Business One Integration

## Boundary

SAP Business One is integrated only through the backend Service Layer client. The React application never receives SAP credentials or calls SAP directly.

## Current implementation

The client manages Service Layer login/logout and cookie-based session state. Read-only calls have bounded transport retry. Financial mutations do not use blind transport retries.

When a POST/PATCH/DELETE ends in an ambiguous transport failure, the client raises a reconciliation-required condition instead of replaying the mutation.

When a mutating request receives a session-expired response, the client does not re-login and replay automatically because the first request may already have reached SAP.

## Implemented mapping references

The repository contains mapper/service code for several internal entities, but **mapping code does not mean the operation is enabled for an operator or verified against live SAP**. The interactive sync contract currently permits only customer/vendor master data and requires `agent:configure`. Financial-document and payment writes are not exposed through the interactive route until an approval-bound execution and reconciliation workflow is implemented.

| Internal entity | SAP Service Layer object | Code-level operation/direction | Source-of-truth policy | Interactive endpoint | Verification state |
|---|---|---|---|---|---|
| Customer | `BusinessPartners` (`CardType=cCustomer`) | Internal customer → SAP create; linked record can be read and compared | Internal record remains local source until conflict is explicitly resolved | Enabled with `agent:configure` | Mapper/unit code only; live tenant not verified |
| Vendor | `BusinessPartners` (`CardType=cSupplier`) | Internal vendor → SAP create; linked record can be read and compared | Internal record remains local source until conflict is explicitly resolved | Enabled with `agent:configure` | Mapper/unit code only; live tenant not verified |
| Purchase order | `PurchaseOrders` | Internal PO → SAP create-once | Local record with persisted SAP document ID; ambiguous result requires reconciliation | Disabled at interactive API contract | Mapping and service code present; not live verified |
| AP invoice | `PurchaseInvoices` | Internal AP invoice → SAP create-once | Local record with persisted SAP document ID; ambiguous result requires reconciliation | Disabled at interactive API contract | Mapping and service code present; not live verified |
| AR invoice | `Invoices` | Internal AR invoice → SAP create-once | Local record with persisted SAP document ID; ambiguous result requires reconciliation | Disabled at interactive API contract | Mapping and service code present; not live verified |
| AR credit memo | `CreditNotes` | Internal AR credit memo → SAP create-once | Local record with persisted SAP document ID; ambiguous result requires reconciliation | Disabled at interactive API contract | Mapping and service code present; not live verified |
| Outgoing payment | `VendorPayments` | Internal outgoing payment → SAP create; references a linked SAP AP invoice | Local payment record with persisted SAP document ID; unknown outcomes require reconciliation | Disabled at interactive API contract | Code itself flags object-version verification; not live verified |
| Incoming payment | `IncomingPayments` | Internal incoming payment → SAP create; references a linked SAP AR invoice | Local payment record with persisted SAP document ID; unknown outcomes require reconciliation | Disabled at interactive API contract | Mapping and service code present; not live verified |
| Goods receipt | `PurchaseDeliveryNotes` | Reference/mapping exists, but no interactive sync schema/service flow confirmed in the current contract | Not asserted beyond the source code | Not advertised | Not verified |
| Journal entry | `JournalEntries` | Object/resource reference exists; no supported sync-agent operation confirmed by the interactive request contract | Not asserted beyond the source code | Not advertised | Not verified |

Required SAP field sets are implemented in the relevant mapper functions; the target release/company-specific required fields and tax/account semantics still require validation against the approved SAP test tenant. Duplicate/create-once checks and reconciliation behavior are covered in source-level tests, but live persistence and duplicate prevention are not verified here.

## Document references used by the code

- Purchase Order → `PurchaseOrders` (22)
- Goods Receipt → `PurchaseDeliveryNotes` (20)
- AP Invoice → `PurchaseInvoices` (18)
- AP Credit Memo → `PurchaseCreditNotes` (19)
- AR Invoice → `Invoices` (13)
- AR Credit Memo → `CreditNotes` (14)
- Incoming Payment → `IncomingPayments` (24)
- Journal Entry → `JournalEntries` (30)
- Business Partner → `BusinessPartners`

The code itself labels some payment mappings for verification. These references should be confirmed against the target SAP Business One release before production posting.

## Source of truth and synchronization

The internal finance database remains the application's transaction/audit source of truth. SAP document identifiers are persisted on internal records where supported. Reconciliation is required when an external result cannot safely be inferred from the transport response.

## Environment separation

SAP configuration is server-side and environment-driven:

- development
- staging/test
- production

No SAP secret is exposed through Vite environment variables or browser responses.

## CI contract testing

Mocked Service Layer transports cover authentication behavior, error parsing, read retry behavior, mutation retry blocking, and mapper behavior. These tests prove local contract behavior only; they do not prove live compatibility with a specific SAP Business One environment.


## Current sync boundary (2026-10-10)

`GET /api/v1/sap/status` is configuration-only. The authenticated `POST /api/v1/sap/verify` sends a bounded read-only `GET BusinessPartners?$top=1&$select=CardCode,CardName,CardType` after server-side authentication and TLS verification. Its response has distinct disabled/configuration/authentication/connectivity/read-result states, checked time, and correlation ID. It has not been run against a real Service Layer here. `SAP_ENABLED=true` with `SAP_VERIFY_SSL=false` fails configuration validation.

The interactive `POST /api/v1/agents/sap-integration/run` now requires `agent:configure`, and `RunSAPIntegrationAgentRequest` accepts only customer/vendor entities. Purchase order, invoice, credit memo and payment mapping/service code remains available internally but cannot be invoked using this interactive request until there is a fully approval-bound financial write/reconciliation flow. Mock tests are blocked/skipped due missing `tenacity`; live SAP verification remains `BLOCKED_EXTERNAL`.
