#!/bin/sh
# Start Postgres (localhost only, sized for a 0.5 GB service), then the API in the foreground.
set -eu
# the database is this container's own, whatever the environment (e.g. a copied .env) says
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 POSTGRES_USER=statnav POSTGRES_PASSWORD=statnav
export POSTGRES_DB=statnav
gosu postgres pg_ctl -D "$PGDATA" -l /tmp/postgres.log -w start \
  -o "-c listen_addresses=127.0.0.1 -c max_connections=10 -c shared_buffers=32MB -c work_mem=8MB"
mkdir -p /app/.cache
exec uv run --no-sync python -m statnav.api --host 0.0.0.0 --port "${PORT:-8000}"
