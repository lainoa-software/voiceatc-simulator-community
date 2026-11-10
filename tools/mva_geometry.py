"""Geometry the MVA chart converters share.

The game has no polygon holes and takes the highest MVA among the areas that contain a point,
so a chart area with a lower area inside one of its holes is cut into hole-free pieces.
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import split


def bridge_cut(shape: Polygon, sliver_area: float) -> list[Polygon]:
    """Cut a polygon with holes into hole-free pieces along the shortest straight cut through each hole.

    Pieces smaller than `sliver_area`, in the polygon's own units, are dropped.
    """
    pieces = [Polygon(shape.exterior, shape.interiors)]
    while any(p.interiors for p in pieces):
        piece = next(p for p in pieces if p.interiors)
        center = Polygon(piece.interiors[0]).representative_point()
        span = math.hypot(*np.subtract(piece.bounds[2:], piece.bounds[:2])) * 2
        best = None
        for degrees in range(0, 180, 3):
            angle = math.radians(degrees)
            dx, dy = math.cos(angle) * span, math.sin(angle) * span
            cutter = LineString([(center.x - dx, center.y - dy), (center.x + dx, center.y + dy)])
            parts = [g for g in split(piece, cutter).geoms if g.area > sliver_area]
            length = cutter.intersection(piece).length
            if len(parts) >= 2 and (best is None or length < best[0]):
                best = (length, parts)
        if best is None:
            raise ValueError("could not cut an area with holes")
        pieces.remove(piece)
        pieces.extend(best[1])
    return pieces
