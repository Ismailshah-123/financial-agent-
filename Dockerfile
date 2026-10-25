# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt alembic.ini ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic ./alembic
COPY app ./app
# Operator command for creating accounts while public registration is disabled.
COPY scripts/create_user.py ./scripts/create_user.py

RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
