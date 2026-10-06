#!/usr/bin/env bash
# Dump the loaded index (provisions, tables, amendments, cross-references, chunks + embeddings)
# so another machine can skip the PDF parse and the Jina embedding run (~1.4M tokens).
#   bash scripts/db_dump.sh [out.dump]        (needs `docker compose up -d db`)
set -euo pipefail
out="${1:-statnav.dump}"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-statnav}" -d "${POSTGRES_DB:-statnav}" \
  --format=custom --compress=9 --no-owner > "$out"
ls -lh "$out"
