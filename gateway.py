"""Code-mode gateway for the airco-harness dsfl-16 test.

Proxies the BGT and CBS wijken en buurten MCP servers (bag.ldproxy.net) and the subsurface-models
server on the host, mounted under the prefixes bgt_, wijkenbuurten_ and subsurface_, and puts
FastMCP's code mode in front: the client sees search, get_schema and execute, and the model's
Python calls the upstream tools inside the sandbox, so only what the code returns reaches the model.

Run: uv run python gateway.py   (serves http://127.0.0.1:18090/mcp)
"""

import asyncio
import os

from fastmcp import Client, FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode, MontySandboxProvider
from fastmcp.server import create_proxy

UPSTREAMS = {
    "bgt": "https://bag.ldproxy.net/bgt/mcp",
    "wijkenbuurten": "https://bag.ldproxy.net/wijkenbuurten/mcp",
    "subsurface": os.environ.get("SUBSURFACE_URL", "http://localhost:18082/mcp"),
}
PORT = int(os.environ.get("CODEMODE_PORT", "18090"))
# GEO=1 adds the generic, stateless geo functions of geo.py under the prefix geo_.
GEO = os.environ.get("GEO") == "1"


async def upstream_instructions() -> str:
    """The instructions each upstream server gives its clients, so the model gets the same guidance as with direct access."""
    parts = []
    for prefix, url in UPSTREAMS.items():
        async with Client(url) as client:
            text = (client.instructions or "").strip()
        parts.append(f"## Server `{prefix}` (tools prefixed `{prefix}_`)\n\n{text or '(no instructions)'}")
    return "\n\n".join(parts)


def build(instructions: str) -> FastMCP:
    header = (
        "This server wraps three MCP servers behind code mode. Use `search` and `get_schema` to find tools, "
        "then `execute` with Python that calls them with `await call_tool(name, params)` and returns only what you need. "
        "Loop, aggregate and compute inside the code: intermediate results stay out of your context. "
        "Tool names carry the prefix of their server: `bgt_`, `wijkenbuurten_`, `subsurface_`. "
        "The subsurface-models server is also connected to you directly: for a borehole you report in your answer, "
        "call its trace tool directly rather than through execute.\n\n"
    )
    if GEO:
        header += (
            "Generic geo functions are available as tools with the prefix `geo_`: coordinate transformation (PROJ, RDNAPTRANS for RD), "
            "measures in a metric CRS (area, length, centroid, a point inside), spatial joins and relations, overlay, grid cells over polygons, "
            "zonal statistics, fetching every page of a collection tool, and simplifying geometry. They are stateless.\n\n"
        )
    gateway = FastMCP(
        "codemode",
        instructions=header + instructions,
        transforms=[
            CodeMode(
                sandbox_provider=MontySandboxProvider(limits={"max_feed_duration_secs": 280, "max_memory": 1_000_000_000, "max_suspensions": 10_000}),
                max_tool_calls=10_000,
                wall_clock_timeout_secs=280,
            )
        ],
    )
    for prefix, url in UPSTREAMS.items():
        gateway.mount(create_proxy(url, name=prefix), namespace=prefix)
    if GEO:
        from geo import build_geo

        gateway.mount(build_geo(UPSTREAMS), namespace="geo")
    return gateway


if __name__ == "__main__":
    build(asyncio.run(upstream_instructions())).run(transport="http", host="127.0.0.1", port=PORT)
