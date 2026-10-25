"""
app.agents
==========
The multi-agent framework.

    base_agent.py    — BaseAgent: the abstract contract every specialized
                        agent implements (permission gating, failure
                        containment, event publication, approval gating).
    schemas.py        — AgentDecision / AgentContext / AgentResult and the
                        rest of the shared decision vocabulary.
    llm_client.py      — LLMClient: the only way agents call an LLM
                        (multi-provider fallback chain).
    prompts/            — prompt templates, one module per agent.
    accounts_payable/   — AccountsPayableAgent: the reference
                        implementation. Read this before building the
                        next agent (Tax, Treasury, ...).
    accounts_receivable/ — AccountsReceivableAgent: collection risk +
                        credit-limit exposure assessment for AR invoices.
    sap_integration/     — SAPIntegrationAgent: syncs Vendor/Customer
                        master data to SAP Business One and flags
                        conflicts/failures for human review rather than
                        silently resolving them. Depends on
                        app.integrations.sap (NOT verified against a
                        real SAP instance — see that package's docstring).

Remaining agents from `app.core.constants.AgentType` follow the same
shape as `accounts_payable/` and `accounts_receivable/`: a subpackage
with `agent.py` (extends `BaseAgent`) and, if it needs LLM reasoning,
its own module under `app.agents.prompts`.
"""
