#!/usr/bin/env bash
# Restore a dump made by db_dump.sh into the compose database (replaces what is there).
#   docker compose up -d db && bash scripts/db_restore.sh statnav.dump
set -euo pipefail
in="${1:-statnav.dump}"
docker compose exec -T db pg_restore -U "${POSTGRES_USER:-statnav}" -d "${POSTGRES_DB:-statnav}" \
  --clean --if-exists --no-owner < "$in"
docker compose exec -T db psql -U "${POSTGRES_USER:-statnav}" -d "${POSTGRES_DB:-statnav}" -Atc \
  "SELECT 'provisions ' || count(*) FROM provisions UNION ALL SELECT 'chunks ' || count(*) FROM chunks"
