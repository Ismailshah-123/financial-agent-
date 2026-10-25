"""
Finance AI Platform — application package.

This package root marks `app` as the top-level Python package for the
entire backend. No runtime logic lives here; it exists so that internal
imports (`from app.core.config import settings`, etc.) resolve consistently
whether the app is run via `uvicorn app.main:app`, pytest, or a Celery
worker entrypoint.
"""

__version__ = "0.1.0"
