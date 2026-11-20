"""Generic, stateless geo functions as MCP tools, for use from code mode.

Nothing here knows about a dataset or a question: coordinate transformation, measures, spatial joins,
grid cells over polygons, zonal statistics, fetching every page of an OGC API collection tool, and
simplifying geometry for output. Geometries are GeoJSON geometry objects; batches are lists.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Literal

import pyproj
from fastmcp import Client, FastMCP
from pyproj.transformer import TransformerGroup
from shapely import STRtree, get_coordinates, set_precision
from shapely.geometry import box, mapping, shape
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union

pyproj.network.set_network_enabled(True)

# WGS84 input is taken as ETRS89 (they differ by less than a metre in the Netherlands), so that the
# ETRS89 -> RD New transformation based on RDNAPTRANS applies, as in Dutch GIS practice.
ALIASES = {"EPSG:4326": "EPSG:4258", "CRS84": "EPSG:4258", "OGC:CRS84": "EPSG:4258", "WGS84": "EPSG:4258", "RD": "EPSG:28992"}
_transformers: dict[tuple[str, str], Any] = {}


def _crs(c: str) -> str:
    c = str(c).strip()
    if c.isdigit():
        c = f"EPSG:{c}"
    return ALIASES.get(c.upper(), c)


def _tf(src: str, dst: str):
    key = (_crs(src), _crs(dst))
    if key not in _transformers:
        group = TransformerGroup(key[0], key[1], always_xy=True)
        _transformers[key] = group.transformers[0]  # best available first
    return _transformers[key]


def _reproject(geom, src: str, dst: str):
    if _crs(src) == _crs(dst):
        return geom
    t = _tf(src, dst)
    return shp_transform(lambda x, y, z=None: t.transform(x, y), geom)


def _geoms(items: list[dict]) -> list:
    return [shape(g.get("geometry", g)) if isinstance(g, dict) else shape(g) for g in items]


def build_geo(upstreams: dict[str, str]) -> FastMCP:
    geo = FastMCP("geo")

    @geo.tool
    def transform(geometries: list[dict], from_crs: str = "EPSG:4326", to_crs: str = "EPSG:28992") -> dict:
        """Transform GeoJSON geometries (or features) between coordinate reference systems with PROJ.
        CRS as 'EPSG:28992', '28992', 'RD', 'EPSG:4326' or 'CRS84'; axis order is always x/lon, y/lat.
        WGS84 is taken as ETRS89, so WGS84 <-> RD New uses the RDNAPTRANS-based transformation."""
        t = _tf(from_crs, to_crs)
        out = [mapping(_reproject(g, from_crs, to_crs)) for g in _geoms(geometries)]
        return {"geometries": out, "transformation": t.description}

    @geo.tool
    def measure(geometries: list[dict], crs: str = "EPSG:4326", metric_crs: str = "EPSG:28992",
                metrics: list[Literal["area", "length", "centroid", "point_inside", "bounds"]] | None = None) -> dict:
        """Measures per geometry, computed in a metric CRS (default RD New, metres): area in m2, length in m,
        centroid, point_inside (a point guaranteed inside the geometry, unlike a centroid of a concave polygon)
        and bounds. Points are returned in both the metric CRS and the input CRS."""
        metrics = metrics or ["area", "length", "centroid", "point_inside", "bounds"]
        rows = []
        for g in _geoms(geometries):
            m = _reproject(g, crs, metric_crs)
            row: dict[str, Any] = {}
            if "area" in metrics:
                row["area"] = m.area
            if "length" in metrics:
                row["length"] = m.length
            for name, pt in (("centroid", m.centroid if "centroid" in metrics else None),
                             ("point_inside", m.representative_point() if "point_inside" in metrics else None)):
                if pt is not None:
                    back = _reproject(pt, metric_crs, crs)
                    row[name] = {"metric": [pt.x, pt.y], "input_crs": [back.x, back.y]}
            if "bounds" in metrics:
                row["bounds"] = list(m.bounds)
            rows.append(row)
        return {"metric_crs": _crs(metric_crs), "results": rows}

    @geo.tool
    def points_in_polygons(points: list[list[float]], polygons: list[dict], polygon_ids: list[str] | None = None,
                           points_crs: str = "EPSG:4326", polygons_crs: str = "EPSG:4326") -> dict:
        """Spatial join: for each point [x, y], the id of the polygon it lies in (null if none; the first if
        several). Polygons may be geometries or features; ids default to the list index."""
        polys = [_reproject(g, polygons_crs, points_crs) for g in _geoms(polygons)]
        ids = polygon_ids or [str(i) for i in range(len(polys))]
        tree = STRtree(polys)
        from shapely import points as mk_points
        pts = mk_points(points)
        pairs = tree.query(pts, predicate="within")
        found: dict[int, str] = {}
        for pi, gi in zip(pairs[0].tolist(), pairs[1].tolist()):
            found.setdefault(pi, ids[gi])
        return {"polygon_id": [found.get(i) for i in range(len(points))]}

    @geo.tool
    def spatial_relation(a: list[dict], b: list[dict], predicate: Literal["intersects", "contains", "within", "touches", "overlaps", "crosses", "covers", "covered_by", "dwithin"] = "intersects",
                         crs_a: str = "EPSG:4326", crs_b: str = "EPSG:4326", distance: float | None = None, metric_crs: str = "EPSG:28992") -> dict:
        """All pairs (i, j) where a[i] <predicate> b[j], computed in a metric CRS; 'dwithin' takes a distance in metres."""
        ga = [_reproject(g, crs_a, metric_crs) for g in _geoms(a)]
        gb = [_reproject(g, crs_b, metric_crs) for g in _geoms(b)]
        tree = STRtree(gb)
        kw = {"distance": distance} if predicate == "dwithin" else {}
        pairs = tree.query(ga, predicate=predicate, **kw)
        return {"pairs": [[i, j] for i, j in zip(pairs[0].tolist(), pairs[1].tolist())]}

    @geo.tool
    def overlay(operation: Literal["intersection", "union", "difference", "symmetric_difference", "union_all"], a: list[dict], b: list[dict] | None = None,
                crs: str = "EPSG:4326", metric_crs: str = "EPSG:28992", return_crs: str | None = None) -> dict:
        """Geometric overlay, pairwise a[i] op b[i], or 'union_all' to dissolve all of a into one geometry.
        Returns geometries and their areas in m2 (computed in the metric CRS)."""
        ga = [_reproject(g, crs, metric_crs) for g in _geoms(a)]
        if operation == "union_all":
            res = [unary_union(ga)]
        else:
            gb = [_reproject(g, crs, metric_crs) for g in _geoms(b or [])]
            res = [getattr(x, operation)(y) for x, y in zip(ga, gb)]
        rc = return_crs or crs
        return {"geometries": [mapping(_reproject(r, metric_crs, rc)) for r in res], "areas": [r.area for r in res]}

    @geo.tool
    def grid_cells(polygons: list[dict], cell_size: float, origin_x: float = 0.0, origin_y: float = 0.0,
                   mode: Literal["centre_inside", "intersects", "fraction"] = "centre_inside",
                   crs: str = "EPSG:4326", grid_crs: str = "EPSG:28992", polygon_ids: list[str] | None = None,
                   max_cells: int = 200_000) -> dict:
        """Cells of a regular grid (in grid_crs, default RD New) over each polygon. A cell's lower-left corner is
        origin + k*cell_size. mode: 'centre_inside' keeps cells whose centre is inside, 'intersects' keeps every
        touched cell, 'fraction' keeps touched cells with the share of the cell area inside the polygon.
        Returns per polygon the cell centres in grid_crs and in the input crs (and fractions)."""
        ids = polygon_ids or [str(i) for i in range(len(polygons))]
        to_in = _tf(grid_crs, crs)
        out, total = [], 0
        from shapely import points as mk_points
        for pid, g in zip(ids, _geoms(polygons)):
            pg = _reproject(g, crs, grid_crs)
            x0, y0, x1, y1 = pg.bounds
            i0, i1 = math.floor((x0 - origin_x) / cell_size), math.floor((x1 - origin_x) / cell_size)
            j0, j1 = math.floor((y0 - origin_y) / cell_size), math.floor((y1 - origin_y) / cell_size)
            cells = [(origin_x + i * cell_size, origin_y + j * cell_size) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]
            if mode == "centre_inside":
                centres = mk_points([(x + cell_size / 2, y + cell_size / 2) for x, y in cells])
                keep = [c for c, inside in zip(cells, pg.contains(centres).tolist()) if inside] if cells else []
                fr = None
            else:
                kept, fr = [], []
                for x, y in cells:
                    c = box(x, y, x + cell_size, y + cell_size)
                    if c.intersects(pg):
                        f = c.intersection(pg).area / c.area
                        if f > 0:
                            kept.append((x, y)); fr.append(f)
                keep = kept
                if mode == "intersects":
                    fr = None
            total += len(keep)
            if total > max_cells:
                raise ValueError(f"more than {max_cells} cells; use larger cells or fewer polygons")
            centres = [[x + cell_size / 2, y + cell_size / 2] for x, y in keep]
            back = [list(to_in.transform(cx, cy)) for cx, cy in centres]
            row = {"id": pid, "count": len(centres), "centres_grid_crs": centres, "centres_input_crs": back}
            if fr is not None:
                row["fractions"] = fr
            out.append(row)
        return {"grid_crs": _crs(grid_crs), "cells": out, "total": total}

    @geo.tool
    def zonal_stats(zones: list[str], values: list[float | None], statistics: list[Literal["count", "sum", "mean", "min", "max", "share_above", "share_below"]],
                    weights: list[float] | None = None, threshold: float | None = None) -> dict:
        """Group values by zone and compute statistics per zone. zones[i] is the zone of values[i] (null values
        are counted as missing). Optional weights (e.g. area fractions) weight sum, mean and shares.
        share_above / share_below: the (weighted) share of values > or < threshold."""
        acc: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0, "missing": 0, "w": 0.0, "sum": 0.0, "above": 0.0, "below": 0.0, "min": math.inf, "max": -math.inf})
        for i, (z, v) in enumerate(zip(zones, values)):
            a = acc[str(z)]
            if v is None:
                a["missing"] += 1
                continue
            w = weights[i] if weights else 1.0
            a["n"] += 1; a["w"] += w; a["sum"] += w * v
            a["min"] = min(a["min"], v); a["max"] = max(a["max"], v)
            if threshold is not None:
                a["above"] += w if v > threshold else 0.0
                a["below"] += w if v < threshold else 0.0
        res = {}
        for z, a in acc.items():
            r: dict[str, Any] = {"missing": a["missing"]}
            for s in statistics:
                if s == "count": r["count"] = a["n"]
                elif s == "sum": r["sum"] = a["sum"]
                elif s == "mean": r["mean"] = a["sum"] / a["w"] if a["w"] else None
                elif s == "min": r["min"] = a["min"] if a["n"] else None
                elif s == "max": r["max"] = a["max"] if a["n"] else None
                elif s == "share_above": r["share_above"] = a["above"] / a["w"] if a["w"] else None
                elif s == "share_below": r["share_below"] = a["below"] / a["w"] if a["w"] else None
            res[z] = r
        return {"zones": res}

    @geo.tool
    async def fetch_all(tool: str, params: dict | None = None, page_size: int = 100, max_features: int = 20_000) -> dict:
        """Call an OGC API collection tool of an upstream server (prefixed name, e.g. 'wijkenbuurten_collection_buurt')
        page by page with limit/offset until all features are fetched, and return one FeatureCollection."""
        prefix, _, name = tool.partition("_")
        if prefix not in upstreams:
            raise ValueError(f"unknown server prefix {prefix!r}; choose from {sorted(upstreams)}")
        params = dict(params or {})
        feats: list = []
        offset = int(params.pop("offset", 0))
        async with Client(upstreams[prefix]) as client:
            while len(feats) < max_features:
                try:
                    r = await client.call_tool(name, {**params, "limit": page_size, "offset": offset})
                except Exception as e:
                    # A server that refuses a page as too large: halve the page and try again.
                    if page_size > 1 and ("more than" in str(e) or "too large" in str(e).lower()):
                        page_size = max(1, page_size // 2)
                        continue
                    raise
                data = r.structured_content if r.structured_content is not None else __import__("json").loads(r.content[0].text)
                page = data.get("features", [])
                feats += page
                matched = data.get("numberMatched")
                if len(page) < page_size or (matched is not None and len(feats) >= matched):
                    break
                offset += page_size
        return {"type": "FeatureCollection", "numberReturned": len(feats), "features": feats[:max_features]}

    @geo.tool
    def simplify(geometries: list[dict], tolerance_m: float = 1.0, crs: str = "EPSG:4326", decimals: int = 6, metric_crs: str = "EPSG:28992") -> dict:
        """Simplify geometries with a tolerance in metres (computed in the metric CRS) and round coordinates,
        to keep output and maps small. Returns geometries in the input CRS and the coordinate counts before and after."""
        out, before, after = [], 0, 0
        for g in _geoms(geometries):
            before += len(get_coordinates(g))
            s = _reproject(_reproject(g, crs, metric_crs).simplify(tolerance_m, preserve_topology=True), metric_crs, crs)
            s = set_precision(s, 10 ** -decimals)
            after += len(get_coordinates(s))
            out.append(mapping(s))
        return {"geometries": out, "coordinates_before": before, "coordinates_after": after}

    return geo
