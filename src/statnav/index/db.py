"""Connection helper and schema application."""

from __future__ import annotations

from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from statnav.config import db_dsn

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(autocommit: bool = False) -> psycopg.Connection:
    """A connection with pgvector registered.

    Long-lived readers (the chat, the API, the MCP server) pass `autocommit=True`: otherwise
    every SELECT leaves the session "idle in transaction" holding a read lock, and
    `statnav.index.load` (TRUNCATE + reload) blocks behind it for as long as the server runs.
    """
    conn = psycopg.connect(db_dsn(), connect_timeout=5, autocommit=autocommit)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
