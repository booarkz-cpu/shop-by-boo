#!/bin/sh
set -eu
alembic upgrade head
if [ "${WORKER_ROLE:-api}" = "worker" ]; then
  exec "$@"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
