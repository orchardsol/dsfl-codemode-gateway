import asyncio, json, time
from fastmcp import Client
CODE = r'''
fc = await call_tool("geo_fetch_all", {"tool": "wijkenbuurten_collection_buurt", "params": {"gemeente": "0307"}, "page_size": 50})
feats = fc["features"]; two = feats[:2]; ids = [f["id"] for f in two]
m = await call_tool("geo_measure", {"geometries": two, "metrics": ["area", "point_inside"]})
g = await call_tool("geo_grid_cells", {"polygons": two, "cell_size": 100, "polygon_ids": ids})
pts = g["cells"][0]["centres_input_crs"][:5] + [[5.0, 52.0]]
j = await call_tool("geo_points_in_polygons", {"points": pts, "polygons": two, "polygon_ids": ids})
z = await call_tool("geo_zonal_stats", {"zones": ["a","a","b"], "values": [0.05, 0.2, None], "statistics": ["count","mean","share_above"], "threshold": 0.1})
t = await call_tool("geo_transform", {"geometries": [{"type": "Point", "coordinates": [5.3872, 52.1552]}]})
r = await call_tool("geo_spatial_relation", {"a": two, "b": feats, "predicate": "touches"})
u = await call_tool("geo_overlay", {"operation": "union_all", "a": two})
s = await call_tool("geo_simplify", {"geometries": two, "tolerance_m": 5})
return {"buurten": len(feats), "areas": [round(x["area"]) for x in m["results"]], "inside": m["results"][0]["point_inside"]["metric"],
        "cells": [c["count"] for c in g["cells"]], "join": j["polygon_id"], "zonal": z["zones"], "rd": t["geometries"][0]["coordinates"], "tf": t["transformation"][:60],
        "touch_pairs": len(r["pairs"]), "union_area": round(u["areas"][0]), "simplify": [s["coordinates_before"], s["coordinates_after"]]}
'''
async def main():
    async with Client("http://127.0.0.1:18091/mcp", timeout=300) as c:
        tools = await c.list_tools(); print("tools:", [t.name for t in tools])
        found = await c.call_tool("search", {"query": "grid cells zonal statistics transform"}); print("search:", found.content[0].text[:400].replace("\n", " "))
        t = time.time(); r = await c.call_tool("execute", {"code": CODE}, raise_on_error=False)
        print("execute:", r.content[0].text[:1500], f"({time.time()-t:.1f} s)")
asyncio.run(main())
