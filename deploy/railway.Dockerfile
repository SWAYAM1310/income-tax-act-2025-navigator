# One image for a free Railway service: Postgres + pgvector holding the index, and the API.
# The index is restored from the published dump at build time, so the database needs no volume
# and no second service (Railway's free plan has $1 a month of credit; see README "Deploy").
#   docker build -f deploy/railway.Dockerfile -t statnav-railway .
#   docker run -p 8000:8000 --env-file .env statnav-railway
FROM pgvector/pgvector:pg16

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

# PGDATA sits outside /var/lib/postgresql/data, a VOLUME in the base image that would discard it
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_INSTALL_DIR=/opt/python \
    PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
    PGDATA=/srv/pgdata POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 \
    POSTGRES_USER=statnav POSTGRES_PASSWORD=statnav POSTGRES_DB=statnav
WORKDIR /app

# the index: parsed Act + embeddings (GitHub release, 19 MB)
ARG DUMP_URL=https://github.com/SWAYAM1310/income-tax-act-2025-navigator/releases/download/index-2026-10-06/statnav-index-2026-10-06.dump
RUN set -eu; \
    curl -fsSL -o /tmp/index.dump "$DUMP_URL"; \
    mkdir -p "$PGDATA"; chown postgres:postgres "$PGDATA"; \
    echo "$POSTGRES_PASSWORD" > /tmp/pw; chown postgres /tmp/pw; \
    gosu postgres initdb -D "$PGDATA" -U "$POSTGRES_USER" --pwfile=/tmp/pw --auth=scram-sha-256; \
    rm /tmp/pw; \
    gosu postgres pg_ctl -D "$PGDATA" -o "-c listen_addresses=127.0.0.1" -w start; \
    export PGPASSWORD="$POSTGRES_PASSWORD"; \
    createdb -h 127.0.0.1 -U "$POSTGRES_USER" "$POSTGRES_DB"; \
    pg_restore -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner /tmp/index.dump; \
    psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
      "SELECT 'provisions ' || count(*) FROM provisions UNION ALL SELECT 'chunks ' || count(*) FROM chunks"; \
    gosu postgres pg_ctl -D "$PGDATA" -m fast -w stop; \
    rm /tmp/index.dump

# dependencies first, so code changes do not reinstall them
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# statnav.config resolves ROOT from the source tree, so the project stays an editable install
COPY src ./src
COPY configs ./configs
COPY results ./results
RUN uv sync --locked --no-dev
COPY deploy/start.sh /usr/local/bin/statnav-start
RUN chmod +x /usr/local/bin/statnav-start

# Railway sets PORT; mount a volume at /app/.cache to keep the Groq ledger and answer cache
EXPOSE 8000
CMD ["statnav-start"]
