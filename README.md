# dsfl-codemode-gateway

A code-mode MCP gateway built with [FastMCP](https://gofastmcp.com) 4.2.2. It puts code mode in front of three existing MCP servers:

- BGT, at `bag.ldproxy.net`
- CBS wijken en buurten, at `bag.ldproxy.net`
- subsurface models

The client sees three tools: `search`, `get_schema` and `execute`. The model writes Python that calls the upstream tools inside a sandbox (Monty). Only what that code returns reaches the model's context.

This was built for the AI-ready DSFL tests, to try "an agent with server-side code execution" as an execution environment.

## What's here

| File | What it is |
| --- | --- |
| `gateway.py` | The gateway. Each upstream server is mounted under its own prefix (`bgt_`, `wijkenbuurten_`, `subsurface_`). The upstream servers' instructions are passed on, so the model gets the same guidance as with direct access. |
| `geo.py` | Optional generic geo functions, mounted under `geo_`. They are stateless and know nothing about a dataset or a question. |
| `gw.sh` | Starts or stops one gateway, found by its port. |
| `probe.py`, `probe_calls.py`, `probe_geo.py` | Smoke tests against a running gateway. |

The geo functions in `geo.py` cover:

- coordinate transformation with PROJ, using RDNAPTRANS for RD New
- measures in a metric CRS
- spatial joins and relations
- overlay
- grid cells over polygons
- zonal statistics
- fetching every page of a collection tool
- simplifying geometry

## Run

You need [uv](https://docs.astral.sh/uv/) and Python 3.14.

```sh
uv sync
./gw.sh start 18090          # plain gateway on http://127.0.0.1:18090/mcp
./gw.sh start 18091 geo      # with the geo_ functions
uv run python probe.py http://127.0.0.1:18090/mcp
./gw.sh stop 18090
```

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `CODEMODE_PORT` | `18090` | Port to serve on; the gateway listens on 127.0.0.1 only. |
| `SUBSURFACE_URL` | `http://localhost:18082/mcp` | The subsurface-models MCP server. |
| `GEO` | unset | Set to `1` to mount `geo.py`. |

Each `execute` program may make up to 10,000 tool calls and is stopped after 280 seconds of wall-clock time. Nothing is kept between `execute` calls.

The gateway needs no credentials: the upstream servers are public.
