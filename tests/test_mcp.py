"""The MCP server, in process: the five tools are registered and the lookups answer."""

import json

import anyio
import pytest
from mcp import Client

from statnav.mcp_server import server


def call(name: str, args: dict):  # noqa: ANN201 - mcp CallToolResult
    async def go():  # noqa: ANN202
        async with Client(server) as c:
            return await c.call_tool(name, args)
    return anyio.run(go)


def test_the_five_tools_are_registered_with_descriptions():
    async def go():  # noqa: ANN202
        async with Client(server) as c:
            return (await c.list_tools()).tools
    tools = {t.name: t for t in anyio.run(go)}
    assert set(tools) == {"search_act", "get_provision", "get_table_rows", "get_amendments", "ask"}
    assert all(t.description for t in tools.values())
    assert set(tools["get_table_rows"].input_schema["properties"]) == {"table_id", "sl_no"}


@pytest.mark.db
def test_lookups_answer_and_a_bad_id_is_a_tool_error():
    try:
        r = call("get_provision", {"provision_id": "s99(2)"})
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"database not reachable: {exc}")
    p = json.loads("".join(c.text for c in r.content))
    assert not r.is_error and p["amendments"][0]["type"] == "substituted"
    rows = call("get_table_rows", {"table_id": "s393:tbl1", "sl_no": "1"}).structured_content
    assert [x["row_id"] for x in rows["result"]] == ["s393:tbl1#1(i)", "s393:tbl1#1(ii)"]
    bad = call("get_provision", {"provision_id": "no-such-id"})
    assert bad.is_error and "no provision" in bad.content[0].text
