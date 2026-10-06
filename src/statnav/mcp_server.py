"""MCP server: the Act as tools for any MCP client (Claude Desktop, MCP Inspector, ...).

    python -m statnav.mcp_server          # stdio transport

Five tools, over the same layers as the HTTP API:

- `search_act(query, k)`      retrieval only (the default version's hybrid retrieval; no LLM)
- `get_provision(id)`         a provision's text, children, amendments (table rows for tables)
- `get_table_rows(table_id)`  rows of a rate table such as `s393:tbl1`, optionally one Sl. No.
- `get_amendments(id)`        Finance Act, 2026 endnotes for a provision and its sub-provisions
- `ask(question)`             a cited answer from the agent (spends Groq tokens)

Ids look like `s2(5)`, `s393(1)(d)`, `sch:XIV:4(3)`, tables `s393:tbl1`, rows `s393:tbl1#1(i)`.
"""

from __future__ import annotations

from functools import lru_cache

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from statnav import repo
from statnav.answer import Answerer
from statnav.api.app import DEFAULT_VERSION, answer_payload

server = MCPServer(
    name="statnav",
    instructions=(
        "Look things up in India's Income-tax Act, 2025 as amended by the Finance Act, 2026. "
        "Use search_act to find provisions, get_provision / get_table_rows / get_amendments to "
        "read them, and ask for a cited answer. Provision ids look like s2(5), s393(1)(d), "
        "sch:XIV:4(3); tables s393:tbl1. Answers are not tax advice."),
)


@lru_cache(maxsize=1)
def _bot() -> Answerer:
    return Answerer.for_version(DEFAULT_VERSION)


def _conn():  # noqa: ANN202 - a psycopg connection, opened on first use
    return _bot().conn


@server.tool()
def search_act(query: str, k: int = 5) -> list[dict]:
    """Find the provisions most relevant to `query` (no LLM call). Returns passages with their
    provision ids, pages and text."""
    hits = _bot().retrieve(query, max(1, min(k, 20)))
    return [{"chunk_id": h["chunk_id"], "provisions": h["provisions"][:12],
             "page_start": h["page_start"], "page_end": h["page_end"], "text": h["text"]}
            for h in hits]


@server.tool()
def get_provision(provision_id: str) -> dict:
    """A provision's own text, its children in order, and its Finance Act, 2026 amendments.
    For a table id (e.g. s393:tbl1) the rows are included."""
    p = repo.provision(_conn(), provision_id)
    if p is None:  # raised, so the client sees a tool error rather than a successful result
        raise ToolError(f"no provision {provision_id!r}; ids look like s2(5) or s393:tbl1")
    return p


@server.tool()
def get_table_rows(table_id: str, sl_no: str | None = None) -> list[dict]:
    """Rows of a rate table (e.g. s393:tbl1 for TDS on payments to residents), optionally only
    serial number `sl_no`. Each row has its cells, rate and threshold."""
    return repo.table_rows(_conn(), table_id, sl_no)


@server.tool()
def get_amendments(provision_id: str) -> list[dict]:
    """Finance Act, 2026 amendments (type, effective date, endnote text, prior text) linked to a
    provision or anything under it."""
    return repo.amendments(_conn(), provision_id)


@server.tool()
def ask(question: str) -> dict:
    """A cited answer to a question about the Act (runs the agent; spends LLM tokens). Refuses
    questions outside the Act (Rules, forms, case law, personal advice)."""
    return answer_payload(_bot().ask(question), DEFAULT_VERSION)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
