"""Coded SID ends and STAR starts, which a generated route may not use as its first or last fix.

Creator decision 2026-10-21: a generated route starts at a published point of a
SID and ends at a published point of a STAR. Some airports end or start their
procedures at airport-local coded points instead (Frankfurt DF163, Paris PG825,
Zurich DER34, Cologne DK634). The route generator excludes them with the same
definition as this module:

- A published ident is in tbl_ea_enroute_waypoints, tbl_d_vhfnavaids,
  tbl_db_enroute_ndbnavaids or tbl_pn_terminal_ndbnavaids.
- A coded point is not published and contains a digit. A letter-only name that
  exists only in tbl_pc_terminal_waypoints (Canadian HAMPO) is not coded.
- A SID end is the last fix (highest seqno) of a (procedure, route type,
  transition) group of any route type. A STAR start is the first fix of such a
  group. Rows with a blank fix are ignored.

Coded points elsewhere (approach fixes, graph nodes) are out of scope.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

_PROCEDURE_ENDS_QUERY = """
    SELECT airport_identifier, waypoint_identifier
    FROM (
        SELECT airport_identifier,
               waypoint_identifier,
               ROW_NUMBER() OVER (
                   PARTITION BY airport_identifier,
                                procedure_identifier,
                                route_type,
                                COALESCE(transition_identifier, '')
                   ORDER BY seqno {direction}
               ) AS end_rank
        FROM {table}
        WHERE TRIM(COALESCE(waypoint_identifier, '')) != ''
    )
    WHERE end_rank = 1
"""


class CodedRouteEnds:
    """Coded SID ends and STAR starts per airport, from one scan of each procedure table."""

    def __init__(self, db_path: Path, *, published: set[str]) -> None:
        self._sid_ends = _coded_procedure_ends(db_path, "tbl_pd_sids", "DESC", published)
        self._star_starts = _coded_procedure_ends(db_path, "tbl_pe_stars", "ASC", published)

    def is_coded_sid_end(self, airport: str, fix: str) -> bool:
        return fix in self._sid_ends.get(airport, ())

    def is_coded_star_start(self, airport: str, fix: str) -> bool:
        return fix in self._star_starts.get(airport, ())


def _coded_procedure_ends(
    db_path: Path, table: str, direction: str, published: set[str]
) -> dict[str, set[str]]:
    ends: dict[str, set[str]] = {}
    try:
        with closing(sqlite3.connect(db_path)) as con:
            for airport, fix in con.execute(_PROCEDURE_ENDS_QUERY.format(table=table, direction=direction)):
                airport = str(airport or "").strip().upper()
                fix = str(fix).strip().upper()
                if airport and fix not in published and any(c.isdigit() for c in fix):
                    ends.setdefault(airport, set()).add(fix)
    except sqlite3.OperationalError:
        pass  # table absent in mock/older navdata: no procedure ends to reject
    return ends
