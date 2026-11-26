#!/bin/sh
set -eu
alembic upgrade head
if [ "$#" -eq 0 ]; then
  set -- uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
fi
exec "$@"
