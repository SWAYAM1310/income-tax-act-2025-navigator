"""Exercise the MCP server the way an MCP client does: launch it over stdio, list its tools and
call each one. The Phase 9 exit check for the MCP side.

    .venv/Scripts/python.exe scripts/mcp_inspect.py          # 4 lookup tools, no LLM tokens
    .venv/Scripts/python.exe scripts/mcp_inspect.py --ask    # also `ask` (spends Groq tokens)

Exits non-zero if a tool is missing or a call fails. To browse the server interactively instead,
run `npx @modelcontextprotocol/inspector .venv/Scripts/python.exe -m statnav.mcp_server`.
"""

from __future__ import annotations

import argparse
import json
import sys

import anyio
from mcp import Client, StdioServerParameters

EXPECTED = {"search_act", "get_provision", "get_table_rows", "get_amendments", "ask"}
CALLS = [
    ("search_act", {"query": "how is agricultural income defined", "k": 3}),
    ("get_provision", {"provision_id": "s2(5)"}),
    ("get_table_rows", {"table_id": "s393:tbl1", "sl_no": "1"}),
    ("get_amendments", {"provision_id": "s99"}),
]


def _payload(result) -> object:  # noqa: ANN001 - mcp CallToolResult
    if result.structured_content is not None:
        return result.structured_content.get("result", result.structured_content)
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except ValueError:
        return text


async def main(ask: bool) -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "statnav.mcp_server"])
    failures = 0
    async with Client(params) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        print(f"tools: {sorted(tools)}")
        if missing := EXPECTED - tools:
            print(f"MISSING: {sorted(missing)}")
            failures += 1
        calls = [*CALLS, ("ask", {"question": "How is agricultural income defined?"})] if ask \
            else CALLS
        for name, args in calls:
            r = await client.call_tool(name, args)
            data = _payload(r)
            status = "ERROR" if r.is_error else "ok"
            failures += r.is_error
            summary = (f"{len(data)} items" if isinstance(data, list)
                       else ", ".join(f"{k}={str(v)[:60]!r}" for k, v in list(data.items())[:3])
                       if isinstance(data, dict) else str(data)[:120])
            print(f"{status:5} {name}({json.dumps(args)}) -> {summary}")
        r = await client.call_tool("get_provision", {"provision_id": "no-such-id"})
        print(f"{'ok' if r.is_error else 'ERROR':5} get_provision(no-such-id) -> tool error "
              f"as expected: {r.is_error}")
        failures += not r.is_error
    print("PASS" if not failures else f"FAIL ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", action="store_true", help="also call `ask` (spends Groq tokens)")
    sys.exit(anyio.run(main, ap.parse_args().ask))
