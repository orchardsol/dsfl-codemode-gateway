import asyncio, time
from fastmcp import Client
CODE = """
import asyncio
async def one(i):
    r = await call_tool("subsurface_subsurface-models.trace", {"modelId": "GEOTOP-v01r6s1-001", "point": {"type": "Point", "coordinates": [5.38 + (i % 40) * 0.0015, 52.15 + (i // 40) * 0.001]}})
    return 1 if isinstance(r, dict) else 0
res = await asyncio.gather(*[one(i) for i in range(1200)])
return sum(res)
"""
async def main():
    async with Client("http://127.0.0.1:18090/mcp", timeout=300) as c:
        t = time.time(); r = await c.call_tool("execute", {"code": CODE}, raise_on_error=False)
        print("1200 traces in one program:", r.content[0].text[:200], f"({time.time()-t:.0f} s)")
asyncio.run(main())
