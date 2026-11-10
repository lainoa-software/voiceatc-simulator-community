#!/usr/bin/env python3
"""Cut each lower MVA area out of any higher area that wholly contains it.

The game takes the highest MVA among the areas that contain a point, so a 1,700 ft control zone
drawn inside a 2,000 ft area reads as 2,000 ft everywhere. This rewrites the higher area without
the lower ones inside it, cut into hole-free pieces (see mva_geometry.bridge_cut), and then checks
on a 0.25 NM grid that the game reads the innermost area's value and nothing else changed.

Needs shapely 2 and numpy (the validators do not):

    python tools/mva_unhide.py E/EH/EHAA/AMSTERDAM_TMA/mva.json [--write]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from shapely import contains_xy
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import polylabel, unary_union

try:
    from .mva_geometry import bridge_cut
except ImportError:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mva_geometry import bridge_cut

SLIVER_DEG2 = 1e-5
NESTED_SHARE = 0.01  # a lower area counts as inside when at most 1% of it pokes out (drawn borders that miss by a hair)
GRID_NM = 0.25


def _shape(area: dict) -> Polygon:
    return Polygon([(lon, lat) for lat, lon in area["polygon"]]).buffer(0)


def _nested(areas: list[dict], shapes: list[Polygon]) -> dict[int, list[int]]:
    """For each area, the lower areas that lie wholly inside it."""
    found: dict[int, list[int]] = {}
    for i, outer in enumerate(shapes):
        for j, inner in enumerate(shapes):
            lower = areas[j]["minimum_altitude_ft"] < areas[i]["minimum_altitude_ft"]
            if lower and inner.difference(outer).area < max(SLIVER_DEG2, NESTED_SHARE * inner.area):
                found.setdefault(i, []).append(j)
    return found


def _pieces(shape) -> list[Polygon]:
    parts = shape.geoms if isinstance(shape, MultiPolygon) else [shape]
    pieces: list[Polygon] = []
    for part in parts:
        if part.area > SLIVER_DEG2:
            pieces.extend(bridge_cut(part, SLIVER_DEG2) if part.interiors else [part])
    return pieces


def _ring(polygon: Polygon) -> list[list[float]]:
    return [[round(lat, 9), round(lon, 9)] for lon, lat in polygon.exterior.coords[:-1]]


def unhide(payload: dict) -> tuple[dict, list[str]]:
    areas = payload["mva_areas"]
    shapes = [_shape(a) for a in areas]
    nested = _nested(areas, shapes)
    report, out = [], []
    for i, area in enumerate(areas):
        if i not in nested:
            out.append(area)
            continue
        cut = shapes[i].difference(unary_union([shapes[j] for j in nested[i]]))
        pieces = _pieces(cut)
        report.append(f"{area['area_id']} ({area['minimum_altitude_ft']}) loses "
                      f"{', '.join(areas[j]['area_id'] for j in nested[i])}: {len(pieces)} piece(s)")
        text = area["labels"][0]["text"] if area.get("labels") else None
        for n, piece in enumerate(pieces, start=1):
            labels = [l for l in area.get("labels", []) if piece.contains(Polygon(_square(l["position"])).centroid)]
            if not labels and text:
                spot = polylabel(piece, tolerance=1e-4)
                labels = [{"text": text, "position": [round(spot.y, 9), round(spot.x, 9)]}]
            out.append({**area, "area_id": area["area_id"] if len(pieces) == 1 else f"{area['area_id']}_{n}",
                        "polygon": _ring(piece), "labels": labels})
    return {**payload, "mva_areas": out}, report


def _square(position: list[float]) -> list[tuple[float, float]]:
    lat, lon = position
    d = 1e-7
    return [(lon - d, lat - d), (lon + d, lat - d), (lon + d, lat + d), (lon - d, lat + d)]


def _game_reading(shapes: list[Polygon], feet: list[int], xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    reading = np.zeros(xs.shape, dtype=int)
    for shape, value in zip(shapes, feet):
        reading = np.where(contains_xy(shape, xs, ys), np.maximum(reading, value), reading)
    return reading


def check(before: dict, after: dict) -> int:
    """Grid points where the fixed file does not read the innermost area's value."""
    areas = before["mva_areas"]
    shapes = [_shape(a) for a in areas]
    nested = _nested(areas, shapes)
    minx, miny, maxx, maxy = unary_union(shapes).bounds
    step_lat = GRID_NM / 60
    step_lon = step_lat / math.cos(math.radians((miny + maxy) / 2))
    xs, ys = np.meshgrid(np.arange(minx, maxx, step_lon), np.arange(miny, maxy, step_lat))
    xs, ys = xs.ravel(), ys.ravel()
    expected = np.zeros(xs.shape, dtype=int)
    for i, (shape, area) in enumerate(zip(shapes, areas)):
        inside = contains_xy(shape, xs, ys)
        for j in nested.get(i, []):
            inside &= ~contains_xy(shapes[j], xs, ys)
        expected = np.where(inside, np.maximum(expected, area["minimum_altitude_ft"]), expected)
    got = _game_reading([_shape(a) for a in after["mva_areas"]], [a["minimum_altitude_ft"] for a in after["mva_areas"]], xs, ys)
    return int(np.count_nonzero(got != expected))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    before = json.loads(args.path.read_text(encoding="utf-8"))
    after, report = unhide(before)
    mismatches = check(before, after)
    print("\n".join(report) or "no hidden areas")
    print(f"grid points that do not read the innermost area: {mismatches}")
    if mismatches:
        return 1
    if args.write and report:
        args.path.write_text(json.dumps(after, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
