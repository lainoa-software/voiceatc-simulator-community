#!/usr/bin/env python3
"""Convert a French AIP minimum vectoring altitude chart (AD 2 xxxx MVA 01, vector PDF) to mva.json.

The chart is read, never traced by hand: the thick black area borders are polygonised into
faces, each face takes the boxed altitude label inside it (or at the end of the label's
leader line), and page points are georeferenced with a quadratic fit to the chart's own
30-minute graticule. The printed boundary coordinates ("49 42 53 N 003 29 05 E") are
used only to check the fit; the report gives each residual in NM.

The game takes the highest MVA among the areas that contain a point, so an area nested
inside a lower one is written as an overlapping polygon, and an area that has a lower area
nested inside it is cut into hole-free pieces.

Needs PyMuPDF, shapely 2 and fontTools (none of them is used by the validators):

    python tools/aip_mva_chart.py AD_2_LFPG_MVA_01.pdf --airport LFPG \
        --out L/LF/LFFF/PARIS_TMA/LFPG/mva.json --check-png lfpg_check.png
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz
import numpy as np
from fontTools.cffLib import CFFFontSet
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import polygonize, snap, unary_union

try:
    from .mva_geometry import bridge_cut
except ImportError:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mva_geometry import bridge_cut

NM_PER_DEG_LAT = 60.0
ALTITUDE_LABEL_RE = re.compile(r"^(?:(\d{4})|FL(\d{3}))$")
CHART_ID_RE = re.compile(r"^AD 2 ([A-Z]{4}) MVA \d{2}$")
GRID_GREY = (0.58, 0.59, 0.60)
PINK = (0.93, 0.05, 0.43)
BORDER_MIN_WIDTH = 0.9
SNAP_TOLERANCE_PT = 0.8
SLIVER_AREA_PT2 = 2.0
MERGE_VERTEX_PT = 0.05


def _close(color: tuple | None, target: tuple, tolerance: float = 0.05) -> bool:
    return color is not None and all(abs(a - b) <= tolerance for a, b in zip(color, target))


def _center(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def _dark(color: tuple | None) -> bool:
    return color is not None and max(color) < 0.3


@dataclass
class Token:
    text: str
    rect: fitz.Rect


@dataclass
class Label:
    text: str
    minimum_altitude_ft: int
    box: fitz.Rect
    anchor: tuple[float, float]
    pink: bool


@dataclass
class Area:
    area_id: str
    minimum_altitude_ft: int
    polygon: Polygon
    labels: list[Label]


# ---- text -------------------------------------------------------------------------------
# The chart fonts are CFF subsets without a ToUnicode map, but their glyph names (MT50, MT48,
# ...) carry the Unicode code point, so text decodes from glyph ids.


def _glyph_tables(doc: fitz.Document, page: fitz.Page) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for xref, _ext, _type, basefont, *_rest in page.get_fonts():
        _name, _ext, _subtype, buffer = doc.extract_font(xref)
        fonts = CFFFontSet()
        fonts.decompile(io.BytesIO(buffer), None)
        charset = fonts[fonts.fontNames[0]].charset
        tables[basefont.split("+", 1)[-1]] = [
            chr(int(name[2:])) if name.startswith("MT") and name[2:].isdigit() else "�" for name in charset
        ]
    return tables


def _span_candidates(span: dict, tables: dict[str, list[str]]) -> list[str]:
    # MuPDF truncates the font name at the style hyphen, so the style flags pick the font,
    # and bold spans are decoded with each bold face (the caller keeps the one that parses).
    family = span["font"].rstrip("-")
    if span["flags"] & 2 and not span["flags"] & 16:
        names = [f"{family}-Oblique"]
    elif span["flags"] & 16:
        names = [f"{family}-BoldObl", f"{family}-Bold"]
    else:
        names = [family]
    decoded = []
    for name in names:
        table = tables.get(name)
        if table is None:
            continue
        decoded.append("".join(table[c[1]] if c[1] < len(table) else "�" for c in span["chars"]))
    return decoded


def _tokens(page: fitz.Page, tables: dict[str, list[str]]) -> list[tuple[list[str], fitz.Rect, dict]]:
    seen: set[tuple] = set()
    tokens = []
    for span in page.get_texttrace():
        key = (tuple(round(v, 1) for v in span["bbox"]), tuple(c[1] for c in span["chars"]))
        if key in seen:  # the chart prints a white halo copy under most text
            continue
        seen.add(key)
        tokens.append((_span_candidates(span, tables), fitz.Rect(span["bbox"]), span))
    return tokens


def _words(tokens, *, gap: float = 2.5) -> list[Token]:
    """Regular-face characters grouped into words by baseline and spacing (spans are not in reading order)."""
    chars: set[tuple[str, float, float, float, float]] = set()
    for candidates, _rect, span in tokens:
        if span["flags"] & 18 or not candidates:
            continue
        for char, raw in zip(candidates[0], span["chars"]):
            chars.add((char, *(round(v, 2) for v in raw[3])))
    ordered = sorted(chars, key=lambda c: (round(c[4]), c[1]))
    words: list[Token] = []
    after_space = False
    for char, x0, y0, x1, y1 in ordered:
        if not char.strip():
            after_space = True
            continue
        last = words[-1] if words and not after_space else None
        after_space = False
        if last is not None and abs(last.rect.y1 - y1) < 1.0 and -0.5 < x0 - last.rect.x1 < gap:
            last.text += char
            last.rect |= fitz.Rect(x0, y0, x1, y1)
        else:
            words.append(Token(char, fitz.Rect(x0, y0, x1, y1)))
    return words


# ---- georeference -----------------------------------------------------------------------


@dataclass
class Georef:
    lat_coef: np.ndarray
    lon_coef: np.ndarray
    control_residuals_nm: list[float]

    @staticmethod
    def _terms(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return np.column_stack([np.ones_like(x), x, y, x * x, x * y, y * y])

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        terms = self._terms(np.array([x]), np.array([y]))
        return float((terms @ self.lat_coef)[0]), float((terms @ self.lon_coef)[0])


def _grid_lines(page: fitz.Page) -> tuple[list[LineString], list[LineString]]:
    """Meridians and parallels: the grey hairline polylines that run across the chart."""
    meridians, parallels = [], []
    for drawing in page.get_drawings():
        if not _close(drawing.get("color"), GRID_GREY) or drawing.get("fill") is not None:
            continue
        points: list[tuple[float, float]] = []
        for item in drawing["items"]:
            if item[0] != "l":
                points = []
                break
            a, b = (item[1].x, item[1].y), (item[2].x, item[2].y)
            if not points:
                points = [a, b]
            elif math.dist(points[-1], a) < 0.05:
                points.append(b)
            else:
                points = []
                break
        if len(points) < 2:
            continue
        line = LineString(points)
        if line.length < 50:  # graduation ticks
            continue
        x0, y0, x1, y1 = line.bounds
        (meridians if (y1 - y0) > (x1 - x0) else parallels).append(line)
    return _merge_collinear(meridians, vertical=True), _merge_collinear(parallels, vertical=False)


def _merge_collinear(lines: list[LineString], *, vertical: bool) -> list[LineString]:
    """The graticule is drawn in several pieces; join pieces of one line (and drop duplicates)."""
    groups: list[list[LineString]] = []
    for line in sorted(lines, key=lambda l: (l.centroid.x if vertical else l.centroid.y)):
        for group in groups:
            if any(line.distance(other) < 1.5 and _same_direction(line, other, vertical) for other in group):
                group.append(line)
                break
        else:
            groups.append([line])
    merged = []
    for group in groups:
        union = unary_union(group)
        merged.append(union if isinstance(union, LineString) else MultiLineString(list(union.geoms)))
    return merged


def _same_direction(a: LineString, b: LineString, vertical: bool) -> bool:
    ax = a.centroid.x if vertical else a.centroid.y
    bx = b.centroid.x if vertical else b.centroid.y
    return abs(ax - bx) < 6.0


def _axis_labels(words: list[Token]) -> tuple[list[tuple[float, fitz.Rect]], list[tuple[float, fitz.Rect]]]:
    """Graticule labels: a degree word ("002°") with its minute word ("30'") beside or under it."""
    degree_words = [w for w in words if re.fullmatch(r"\d{2,3}°", w.text)]
    minute_words = [w for w in words if re.fullmatch(r"\d{2}[’'\u0092]", w.text)]
    longitudes, latitudes = [], []
    for degree in degree_words:
        nearest = min(minute_words, key=lambda m: math.dist(m.rect.tl, degree.rect.tl), default=None)
        if nearest is None or math.dist(nearest.rect.tl, degree.rect.tl) > 16:
            continue
        value = int(degree.text[:-1]) + int(nearest.text[:2]) / 60.0
        (longitudes if len(degree.text) == 4 else latitudes).append((value, degree.rect | nearest.rect))
    return longitudes, latitudes


def fit_georef(page: fitz.Page, words: list[Token]) -> tuple[Georef, list[dict]]:
    meridians, parallels = _grid_lines(page)
    longitudes, latitudes = _axis_labels(words)
    page_bottom = max(line.bounds[3] for line in meridians)
    page_left = min(line.bounds[0] for line in parallels)

    def label_for(line, labels, *, vertical: bool) -> float:
        if vertical:
            end = min(line.coords if isinstance(line, LineString) else line.geoms[0].coords, key=lambda p: -p[1])
            ref = (end[0], page_bottom)
            key = lambda item: abs(item[1].x0 - ref[0]) + abs(item[1].y0 - ref[1]) * 0.2
        else:
            pts = [p for g in (line.geoms if hasattr(line, "geoms") else [line]) for p in g.coords]
            end = min(pts, key=lambda p: p[0])
            ref = (page_left, end[1])
            key = lambda item: abs(item[1].y1 - ref[1]) + abs(item[1].x0 - ref[0]) * 0.2
        value, rect = min(labels, key=key)
        if key((value, rect)) > 30:
            raise ValueError(f"no graticule label near the line ending at {end}")
        return value

    lon_of = [label_for(m, longitudes, vertical=True) for m in meridians]
    lat_of = [label_for(p, latitudes, vertical=False) for p in parallels]
    if len(set(lon_of)) != len(lon_of) or len(set(lat_of)) != len(lat_of):
        raise ValueError(f"graticule labels are ambiguous: lon {lon_of} lat {lat_of}")

    xs, ys, lats, lons = [], [], [], []
    for meridian, lon in zip(meridians, lon_of):
        for parallel, lat in zip(parallels, lat_of):
            crossing = meridian.intersection(parallel)
            if crossing.is_empty:
                continue
            point = crossing if isinstance(crossing, Point) else crossing.centroid
            xs.append(point.x)
            ys.append(point.y)
            lats.append(lat)
            lons.append(lon)
    x, y = np.array(xs), np.array(ys)
    terms = Georef._terms(x, y)
    lat_coef, *_ = np.linalg.lstsq(terms, np.array(lats), rcond=None)
    lon_coef, *_ = np.linalg.lstsq(terms, np.array(lons), rcond=None)
    georef = Georef(lat_coef, lon_coef, [])
    controls = []
    for px, py, lat, lon in zip(xs, ys, lats, lons):
        fit_lat, fit_lon = georef.latlon(px, py)
        controls.append({"lat": lat, "lon": lon, "residual_nm": distance_nm((fit_lat, fit_lon), (lat, lon))})
    georef.control_residuals_nm = [c["residual_nm"] for c in controls]
    return georef, controls


def distance_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    mean_lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * NM_PER_DEG_LAT, (a[1] - b[1]) * NM_PER_DEG_LAT * math.cos(mean_lat))


# ---- linework and faces ------------------------------------------------------------------


def _path_lines(drawing: dict) -> list[LineString]:
    lines = []
    for item in drawing["items"]:
        kind = item[0]
        if kind == "l":
            lines.append(LineString([(item[1].x, item[1].y), (item[2].x, item[2].y)]))
        elif kind == "c":
            p0, p1, p2, p3 = item[1:5]
            pts = []
            for i in range(13):
                t = i / 12
                pts.append(
                    (
                        (1 - t) ** 3 * p0.x + 3 * (1 - t) ** 2 * t * p1.x + 3 * (1 - t) * t * t * p2.x + t**3 * p3.x,
                        (1 - t) ** 3 * p0.y + 3 * (1 - t) ** 2 * t * p1.y + 3 * (1 - t) * t * t * p2.y + t**3 * p3.y,
                    )
                )
            lines.append(LineString(pts))
        elif kind == "re":
            r = item[1]
            lines.append(LineString([r.tl, r.tr, r.br, r.bl, r.tl]))
    return lines


def _closed_polygon(drawing: dict) -> Polygon:
    merged = unary_union(_path_lines(drawing))
    faces = list(polygonize(merged))
    if not faces:
        raise ValueError(f"path at {drawing['rect']} is not closed")
    return max(faces, key=lambda f: f.area)


def border_faces(page: fitz.Page) -> list[Polygon]:
    lines: list[LineString] = []
    for drawing in page.get_drawings():
        if drawing.get("fill") is not None or not _dark(drawing.get("color")):
            continue
        if (drawing.get("width") or 0) < BORDER_MIN_WIDTH or drawing.get("dashes") not in (None, "[] 0"):
            continue
        lines.extend(_path_lines(drawing))
    network = unary_union(lines)
    network = unary_union(snap(network, network, SNAP_TOLERANCE_PT))
    faces = [face for face in polygonize(network) if face.area > SLIVER_AREA_PT2]
    return faces


# ---- labels -----------------------------------------------------------------------------


def altitude_labels(page: fitz.Page, tokens) -> list[Label]:
    drawings = page.get_drawings()
    boxes = [
        d for d in drawings if d.get("fill") is not None and (max(d["fill"]) < 0.2 or _close(d["fill"], PINK))
    ]
    leaders = [
        d
        for d in drawings
        if d.get("fill") is None
        and (_dark(d.get("color")) or _close(d.get("color"), PINK))
        and len(d["items"]) == 1
        and d["items"][0][0] == "l"
        and (d.get("width") or 0) < BORDER_MIN_WIDTH
    ]
    labels = []
    for candidates, rect, span in tokens:
        if not span["flags"] & 16:
            continue
        text = next((c for c in candidates if ALTITUDE_LABEL_RE.fullmatch(c)), None)
        if text is None:
            continue
        box_drawing = next((b for b in boxes if fitz.Rect(b["rect"]).contains(_center(rect))), None)
        if box_drawing is None:
            continue
        box = fitz.Rect(box_drawing["rect"])
        match = ALTITUDE_LABEL_RE.fullmatch(text)
        feet = int(match.group(1)) if match.group(1) else int(match.group(2)) * 100
        anchor = (box.x0 + box.width / 2, box.y0 + box.height / 2)
        grown = fitz.Rect(box.x0 - 1.5, box.y0 - 1.5, box.x1 + 1.5, box.y1 + 1.5)
        for leader in leaders:
            a, b = leader["items"][0][1], leader["items"][0][2]
            if grown.contains(a) and not grown.contains(b):
                anchor = (b.x, b.y)
            elif grown.contains(b) and not grown.contains(a):
                anchor = (a.x, a.y)
        labels.append(Label(text, feet, box, anchor, _close(box_drawing["fill"], PINK)))
    return labels


def pink_areas(page: fitz.Page) -> list[Polygon]:
    """Prohibited areas the chart gives their own MVA (P 23): pink closed outlines."""
    polygons = []
    for drawing in page.get_drawings():
        if drawing.get("fill") is None and _close(drawing.get("color"), PINK) and len(drawing["items"]) > 4:
            polygons.append(_closed_polygon(drawing))
    return polygons


def radar_exclusion(page: fitz.Page, words: list[Token]) -> Polygon | None:
    """The "RADAR" quadrilateral of note (3), drawn as a ring at the end of its leader line."""
    radar = next((w for w in words if w.text == "RADAR"), None)
    if radar is None:
        return None
    drawings = page.get_drawings()
    box = next(
        (fitz.Rect(d["rect"]) for d in drawings if d["items"] and d["items"][0][0] == "re" and fitz.Rect(d["rect"]).contains(_center(radar.rect))),
        radar.rect,
    )
    grown = fitz.Rect(box.x0 - 2, box.y0 - 2, box.x1 + 2, box.y1 + 2)
    for d in drawings:
        if not _dark(d.get("color")) or len(d["items"]) != 1 or d["items"][0][0] != "l":
            continue
        a, b = d["items"][0][1], d["items"][0][2]
        far = b if grown.contains(a) else a if grown.contains(b) else None
        if far is None:
            continue
        for ring in drawings:
            if _dark(ring.get("color")) and ring.get("fill") is None and all(i[0] == "c" for i in ring["items"]):
                r = fitz.Rect(ring["rect"])
                if math.dist((r.x0 + r.width / 2, r.y0 + r.height / 2), (far.x, far.y)) < 1.0:
                    return _closed_polygon(ring)
    raise ValueError("RADAR note found but no ring at the end of its leader line")


# ---- assembly ---------------------------------------------------------------------------


def build_areas(faces: list[Polygon], labels: list[Label], pinks: list[Polygon], radar: Polygon | None) -> tuple[list[Area], list[str]]:
    problems: list[str] = []
    face_labels: list[list[Label]] = [[] for _ in faces]
    pink_labels = [label for label in labels if label.pink]
    for label in labels:
        if label.pink:
            continue
        hits = [i for i, face in enumerate(faces) if face.contains(Point(label.anchor))]
        if len(hits) != 1:
            problems.append(f"label {label.text} at {label.anchor} falls in {len(hits)} faces")
            continue
        face_labels[hits[0]].append(label)

    altitudes: list[int | None] = []
    for i, face in enumerate(faces):
        values = {label.minimum_altitude_ft for label in face_labels[i]}
        if len(values) != 1:
            problems.append(f"face {i} at {face.representative_point().coords[0]} has labels {sorted(values)}")
            altitudes.append(None)
        else:
            altitudes.append(values.pop())

    areas: list[Area] = []
    counts: dict[str, int] = {}

    def add(text: str, feet: int, polygon: Polygon, area_labels: list[Label]) -> None:
        counts[text] = counts.get(text, 0) + 1
        areas.append(Area(f"{text}_{counts[text]}", feet, polygon, area_labels))

    for i, face in enumerate(faces):
        if altitudes[i] is None:
            continue
        nested_lower = [
            j for j, other in enumerate(faces)
            if j != i and altitudes[j] is not None and altitudes[j] < altitudes[i]
            and any(Polygon(ring).contains(other.representative_point()) for ring in face.interiors)
        ]
        pieces = bridge_cut(face, SLIVER_AREA_PT2) if nested_lower else [Polygon(face.exterior)]
        text = face_labels[i][0].text
        for piece in pieces:
            inside = [label for label in face_labels[i] if piece.buffer(0.5).contains(Point(label.anchor))]
            add(text, altitudes[i], piece, inside)

    for polygon in pinks:
        label = next((l for l in pink_labels if polygon.buffer(1.0).contains(Point(l.anchor))), None)
        if label is None:
            problems.append(f"pink area at {polygon.representative_point().coords[0]} has no label")
            continue
        areas.append(Area("P23", label.minimum_altitude_ft, polygon, [label]))

    if radar is not None:
        host = next((i for i, face in enumerate(faces) if face.contains(radar.centroid)), None)
        if host is None or altitudes[host] is None:
            problems.append("RADAR ring lies in no labelled face")
        else:
            # Excluded from the area it sits in, it keeps the MVA of the area around that one.
            neighbours = [
                altitudes[j] for j, other in enumerate(faces)
                if j != host and altitudes[j] is not None and other.exterior.intersection(faces[host].exterior).length > 1.0
                or (j != host and any(Polygon(r).contains(faces[host].representative_point()) for r in other.interiors))
            ]
            surround = max((a for a in neighbours if a is not None and a > altitudes[host]), default=None)
            if surround is None:
                problems.append("RADAR ring has no higher surrounding area")
            else:
                areas.append(Area("RADAR", surround, radar, []))
    return areas, problems


def check_coordinates(words: list[Token], faces: list[Polygon], georef: Georef) -> list[dict]:
    """Residual of each printed boundary coordinate against the nearest border vertex."""
    def value_before(index: int, degree_digits: int) -> float | None:
        parts = words[index - 3 : index]
        baseline = words[index].rect.y1
        if len(parts) != 3 or any(abs(w.rect.y1 - baseline) > 0.5 for w in parts):
            return None
        texts = [w.text for w in parts]
        if not re.fullmatch(rf"\d{{{degree_digits}}} \d{{2}} \d{{2}}", " ".join(texts)):
            return None
        return int(texts[0]) + int(texts[1]) / 60 + int(texts[2]) / 3600

    printed = []
    for i, north in enumerate(words):
        if north.text != "N" or (lat := value_before(i, 2)) is None:
            continue
        for j, east in enumerate(words):
            below = east.rect.y1 - north.rect.y1
            if east.text == "E" and 4 < below < 10 and abs(east.rect.x1 - north.rect.x1) < 3:
                lon = value_before(j, 3)
                if lon is not None:
                    box = fitz.Rect(words[i - 3].rect) | north.rect | words[j - 3].rect | east.rect
                    printed.append((lat, lon, box))
    outline = unary_union(faces)
    vertices = set(outline.exterior.coords) if isinstance(outline, Polygon) else {pt for face in faces for pt in face.exterior.coords}
    results = []
    for lat, lon, box in printed:
        center = (box.x0 + box.width / 2, box.y0 + box.height / 2)
        vertex = min(vertices, key=lambda v: math.dist(v, center))
        fit = georef.latlon(*vertex)
        results.append(
            {
                "printed": _dms(lat, lon),
                "page_vertex": [round(vertex[0], 2), round(vertex[1], 2)],
                "label_to_vertex_pt": round(math.dist(vertex, center), 1),
                "residual_nm": round(distance_nm(fit, (lat, lon)), 3),
                "lat": lat,
                "lon": lon,
            }
        )
    return results


def _dms(lat: float, lon: float) -> str:
    def part(value: float, width: int) -> str:
        total = round(value * 3600)
        return f"{total // 3600:0{width}d} {total % 3600 // 60:02d} {total % 60:02d}"

    return f"{part(lat, 2)} N {part(lon, 3)} E"


def convert(pdf: Path, airport: str) -> dict:
    doc = fitz.open(pdf)
    page = doc[0]
    tables = _glyph_tables(doc, page)
    tokens = _tokens(page, tables)
    words = _words(tokens)
    chart_ids = [c for candidates, _r, _s in tokens for c in candidates if CHART_ID_RE.fullmatch(c)]
    if not chart_ids or CHART_ID_RE.fullmatch(chart_ids[0]).group(1) != airport:
        raise ValueError(f"{pdf} is not an MVA chart of {airport} (found {chart_ids})")

    georef, controls = fit_georef(page, words)
    faces = border_faces(page)
    labels = altitude_labels(page, tokens)
    pinks = pink_areas(page)
    radar = radar_exclusion(page, words)
    areas, problems = build_areas(faces, labels, pinks, radar)
    coordinates = check_coordinates(words, faces, georef)

    snapped = {}
    for check in coordinates:
        if check["label_to_vertex_pt"] < 25:
            snapped[tuple(check["page_vertex"])] = (check["lat"], check["lon"])

    def to_latlon(x: float, y: float) -> list[float]:
        exact = snapped.get((round(x, 2), round(y, 2)))
        lat, lon = exact if exact else georef.latlon(x, y)
        return [round(lat, 6), round(lon, 6)]

    mva_areas = []
    for area in areas:
        ring = Polygon(area.polygon.exterior)
        if ring.exterior.is_ccw:  # page y points down, so clockwise on the page is counter-clockwise on the map
            ring = Polygon(list(ring.exterior.coords)[::-1])
        coords = list(ring.exterior.coords)
        # Snapping leaves vertex pairs a few hundredths of a point apart; keep one of each.
        kept = [coords[0]] + [c for prev, c in zip(coords, coords[1:]) if math.dist(prev, c) > MERGE_VERTEX_PT]
        if math.dist(kept[0], kept[-1]) <= MERGE_VERTEX_PT:
            kept[-1] = kept[0]
        else:
            kept.append(kept[0])
        deduped = [to_latlon(x, y) for x, y in kept]
        row = {"area_id": area.area_id, "minimum_altitude_ft": area.minimum_altitude_ft, "polygon": deduped}
        if area.labels:
            row["labels"] = [
                {"text": label.text, "position": to_latlon(label.box.x0 + label.box.width / 2, label.box.y0 + label.box.height / 2)}
                for label in area.labels
            ]
        mva_areas.append(row)
    return {
        "payload": {"airport": airport, "mva_areas": mva_areas},
        "report": {
            "chart": chart_ids[0],
            "faces": len(faces),
            "labels": [(l.text, [round(v, 1) for v in l.anchor]) for l in labels],
            "areas": [(a.area_id, a.minimum_altitude_ft, round(a.polygon.area, 1)) for a in areas],
            "graticule_points": len(controls),
            "graticule_max_residual_nm": round(max(georef.control_residuals_nm), 4),
            "coordinate_checks": coordinates,
            "coordinate_max_residual_nm": max((c["residual_nm"] for c in coordinates), default=None),
            "problems": problems,
        },
        "areas": areas,
        "page": page,
    }


def render_check(result: dict, out: Path) -> None:
    page: fitz.Page = result["page"]
    shape = page.new_shape()
    colors = [(0.85, 0.1, 0.1), (0.1, 0.55, 0.1), (0.1, 0.25, 0.85), (0.8, 0.45, 0.0), (0.55, 0.0, 0.65), (0.0, 0.6, 0.6)]
    for index, area in enumerate(result["areas"]):
        color = colors[index % len(colors)]
        points = [fitz.Point(x, y) for x, y in area.polygon.exterior.coords]
        shape.draw_polyline(points)
        shape.finish(color=color, fill=color, fill_opacity=0.18, width=0.6, closePath=True)
        spot = area.polygon.representative_point()
        shape.insert_text(fitz.Point(spot.x - 12, spot.y + 3), f"{area.area_id} {area.minimum_altitude_ft}", fontsize=5.5, color=color)
    shape.commit()
    page.get_pixmap(dpi=200).save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--airport", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check-png", type=Path)
    args = parser.parse_args()
    result = convert(args.pdf, args.airport.upper())
    report = result["report"]
    print(json.dumps(report, indent=2, default=str))
    if report["problems"]:
        print("not written: the chart did not convert cleanly", file=sys.stderr)
        return 1
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(result["payload"], indent=2) + "\n"
        args.out.write_text(text, encoding="utf-8", newline="\n")
    if args.check_png:
        render_check(result, args.check_png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
