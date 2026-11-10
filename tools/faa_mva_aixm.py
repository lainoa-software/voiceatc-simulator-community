#!/usr/bin/env python3
"""Convert an FAA minimum vectoring altitude chart (AIXM 5.1 from aeronav.faa.gov) to mva.json.

The FAA publishes every TRACON's MVA chart as AIXM: one Airspace per sector, its altitude in
minimumLimit and its outline as polygon patches with holes. The game has no holes and takes
the highest MVA among the areas that contain a point, so a hole is dropped when everything in
it is at least as high, and the sector is cut into hole-free pieces only when a lower sector
sits in one of its holes.

--check replays the game's lookup over a grid of points and counts the points where it
disagrees with the chart. A file is only good when that count is 0.

Needs shapely 2 and numpy (neither is used by the validators):

    python tools/faa_mva_aixm.py N90_MVA_FUS3.xml --airport KJFK \
        --out K/KZNY/JFK_TMA/mva.json --check
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.ops import polylabel

try:
    from .mva_geometry import bridge_cut
except ImportError:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mva_geometry import bridge_cut

GML = "{http://www.opengis.net/gml/3.2}"
AIXM = "{http://www.aixm.aero/schema/5.1}"
SLIVER_AREA_DEG2 = 1e-9
# About 0.03 NM2: FAA sectors that should meet leave gaps and overlaps smaller than this.
HOLE_TOLERANCE_DEG2 = 1e-5
CHECK_SPACING_NM = 0.25


@dataclass
class Sector:
    name: str
    minimum_altitude_ft: int
    shape: Polygon


def _ring(pos_list: str) -> list[tuple[float, float]]:
    values = [float(v) for v in pos_list.split()]
    return list(zip(values[0::2], values[1::2]))


def read_sectors(xml_path: Path) -> tuple[str, list[Sector]]:
    root = ET.parse(xml_path).getroot()
    chart = (root.findtext(f"{GML}description") or xml_path.stem).strip()
    sectors: list[Sector] = []
    for airspace in root.iter(f"{AIXM}Airspace"):
        name = (airspace.findtext(f".//{AIXM}name") or "").strip()
        limit = airspace.find(f".//{AIXM}minimumLimit")
        if limit is None or limit.get("uom") != "FT":
            raise ValueError(f"{xml_path}: sector {name} has no minimumLimit in FT")
        for patch in airspace.iter(f"{GML}PolygonPatch"):
            exterior = _ring(patch.findtext(f"{GML}exterior/{GML}LinearRing/{GML}posList"))
            holes = [_ring(r.findtext(f"{GML}LinearRing/{GML}posList")) for r in patch.findall(f"{GML}interior")]
            sectors.append(Sector(name, int(float(limit.text)), Polygon(exterior, holes)))
    if not sectors:
        raise ValueError(f"{xml_path}: no MVA sectors")
    return chart, sectors


def game_pieces(sectors: list[Sector]) -> list[tuple[Sector, Polygon]]:
    pieces: list[tuple[Sector, Polygon]] = []
    for sector in sectors:
        lower_in_hole = any(
            other.minimum_altitude_ft < sector.minimum_altitude_ft
            and Polygon(hole).intersection(other.shape).area > HOLE_TOLERANCE_DEG2
            for hole in sector.shape.interiors
            for other in sectors
            if other is not sector
        )
        uncovered_hole = any(
            Polygon(hole).difference(shapely.union_all([o.shape for o in sectors if o is not sector])).area > HOLE_TOLERANCE_DEG2
            for hole in sector.shape.interiors
        )
        if lower_in_hole or uncovered_hole:
            pieces.extend((sector, piece) for piece in bridge_cut(sector.shape, SLIVER_AREA_DEG2))
        else:
            pieces.append((sector, Polygon(sector.shape.exterior)))
    return pieces


def _latlon(x: float, y: float) -> list[float]:
    return [round(y, 6), round(x, 6)]


def build_payload(airport: str, pieces: list[tuple[Sector, Polygon]]) -> dict:
    totals: dict[str, int] = {}
    for sector, _piece in pieces:
        totals[sector.name] = totals.get(sector.name, 0) + 1
    seen: dict[str, int] = {}
    areas = []
    for sector, piece in pieces:
        seen[sector.name] = seen.get(sector.name, 0) + 1
        area_id = sector.name if totals[sector.name] == 1 else f"{sector.name}_{seen[sector.name]}"
        label = polylabel(piece, tolerance=1e-4)
        areas.append({
            "area_id": area_id,
            "minimum_altitude_ft": sector.minimum_altitude_ft,
            "polygon": [_latlon(x, y) for x, y in piece.exterior.coords],
            "labels": [{"text": str(sector.minimum_altitude_ft), "position": _latlon(label.x, label.y)}],
        })
    return {"airport": airport, "mva_areas": areas}


def check(sectors: list[Sector], payload: dict) -> dict:
    """Count grid points where the game's highest-area lookup disagrees with the chart."""
    minx, miny, maxx, maxy = shapely.union_all([s.shape for s in sectors]).bounds
    step_lat = CHECK_SPACING_NM / 60.0
    step_lon = step_lat / math.cos(math.radians((miny + maxy) / 2))
    xs, ys = np.meshgrid(np.arange(minx, maxx, step_lon), np.arange(miny, maxy, step_lat))
    xs, ys = xs.ravel(), ys.ravel()

    chart = np.zeros(xs.shape, dtype=int)
    overlaps = np.zeros(xs.shape, dtype=int)
    for sector in sectors:
        inside = shapely.contains_xy(sector.shape, xs, ys)
        overlaps += inside
        chart = np.where(inside, np.maximum(chart, sector.minimum_altitude_ft), chart)

    game = np.zeros(xs.shape, dtype=int)
    for area in payload["mva_areas"]:
        ring = Polygon([(lon, lat) for lat, lon in area["polygon"]])
        game = np.where(shapely.contains_xy(ring, xs, ys), np.maximum(game, area["minimum_altitude_ft"]), game)

    wrong = chart != game
    return {
        "points": int(xs.size),
        "covered_points": int((chart > 0).sum()),
        "mismatches": int(wrong.sum()),
        "mismatch_examples": [[round(float(y), 5), round(float(x), 5), int(c), int(g)]
                              for x, y, c, g in zip(xs[wrong][:5], ys[wrong][:5], chart[wrong][:5], game[wrong][:5])],
        "chart_overlap_points": int((overlaps > 1).sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("xml", type=Path)
    parser.add_argument("--airport", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    chart, sectors = read_sectors(args.xml)
    pieces = game_pieces(sectors)
    payload = build_payload(args.airport.upper(), pieces)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    report = {"chart": chart, "sectors": len(sectors), "areas": len(payload["mva_areas"]),
              "cut_sectors": sorted({s.name for s, _p in pieces if sum(1 for o, _q in pieces if o is s) > 1})}
    if args.check:
        report["check"] = check(sectors, payload)
    print(json.dumps(report, indent=2))
    return 1 if args.check and report["check"]["mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
