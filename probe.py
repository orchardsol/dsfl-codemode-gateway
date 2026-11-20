"""Probe the code-mode gateway: tools and their definition size, then one aggregation and one trace in the sandbox."""

import asyncio
import json
import sys

from fastmcp import Client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18090/mcp"

CODE = """
r = await call_tool("bgt_process_aggregate-features", {
    "source": {"collection": "pand", "parameters": {"gemeentecode": "0307", "relatieveHoogteligging": 0}},
    "groupBy": ["buurtcode"], "aggregates": [{"function": "sum", "property": "$area"}], "limit": 200})
groups = r["groups"] if isinstance(r, dict) else None
t = await call_tool("subsurface_subsurface-models.trace", {"modelId": "GEOTOP-v01r6s1-001", "point": {"type": "Point", "coordinates": [5.3905, 52.157]}})
return {"aggregate_type": type(r).__name__, "groups": len(groups) if groups else None, "first": groups[0] if groups else str(r)[:300],
        "trace_type": type(t).__name__, "trace_keys": list(t.keys())[:10] if isinstance(t, dict) else str(t)[:300]}
"""


async def main() -> None:
    async with Client(URL) as client:
        instructions = client.instructions or ""
        tools = await client.list_tools()
        size = len(json.dumps([t.model_dump(mode="json") for t in tools]))
        print("tools:", [t.name for t in tools], "| definitions:", size, "chars | instructions:", len(instructions), "chars")
        found = await client.call_tool("search", {"query": "aggregate features trace"})
        print("search:", str(found.content[0].text)[:900])
        result = await client.call_tool("execute", {"code": CODE})
        print("execute:", str(result.content[0].text)[:1500])


asyncio.run(main())
