#!/bin/sh
set -e
echo "=== Running Alembic Migrations ==="
alembic upgrade head
echo "=== Starting FastAPI Server ==="
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}