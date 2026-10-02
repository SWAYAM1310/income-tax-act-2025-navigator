"""Database health check: connectivity plus the pgvector extension."""

from __future__ import annotations

import psycopg

from statnav.config import db_dsn


def check() -> str:
    with psycopg.connect(db_dsn(), connect_timeout=5) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        pg = conn.execute("SHOW server_version").fetchone()[0]
        vec = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()[0]
    return f"postgres {pg}, pgvector {vec}"


if __name__ == "__main__":
    print(check())
