"""
app.workers
===========
Celery task definitions and the worker app instance, for anything that
shouldn't run inline in an HTTP request.

    celery_app.py   — the Celery application instance (broker/backend
                        config, run with `celery -A app.workers.celery_app
                        worker --loglevel=info`)
    tasks.py         — run_accounts_payable_agent_task: async batch/
                        scheduled invocation of AccountsPayableAgent

Scheduled jobs (nightly bank reconciliation, recurring invoice checks)
and further async agent tasks are added here alongside the agents that
need them.
"""
