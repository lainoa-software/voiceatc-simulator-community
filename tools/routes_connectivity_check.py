#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from collections import deque
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROUTES_PATH = ROOT / "ROUTES" / "routes.tsv"
RELATED_ROOT = ROOT.parent
GRAPH_SCHEMA_VERSION = "7"

# Oceanic lat/lon fixes ("59N142W", "0330N13300E"). These are first-class route
# points for every flight planner but appear in no navdata table and in no
# compacted-graph node, so they have to be recognised by shape.
COORDINATE_FIX_RE = re.compile(r"^\d{2,4}[NS]\d{3,5}[EW]$")


@dataclass(frozen=True)
class RouteRow:
    line_number: int
    origin: str
    dest: str
    route: str
    creation_airac: str
    author: str


@dataclass(frozen=True)
class Finding:
    line_number: int
    severity: str
    code: str
    detail: str


@dataclass(frozen=True)
class ValidationSummary:
    airac: str
    routes_checked: int
    errors: tuple[Finding, ...]
    warnings: tuple[Finding, ...]
    graph_db: Path | None
    navdata_db: Path | None

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class RouteSegment:
    from_token: str
    connector: str
    to_token: str


class GraphIndex:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.node_ids_by_ident: dict[str, set[int]] = {}
        self.airway_adj: dict[str, dict[int, set[int]]] = {}
        self.airway_nodes: dict[str, set[int]] = {}
        self.airway_path_cache: dict[tuple[str, str, str], bool] = {}
        self.dct_edges: set[tuple[int, int]] = set()
        self._load()

    def _load(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        schema_version = cur.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if not schema_version or str(schema_version["value"]).strip() != GRAPH_SCHEMA_VERSION:
            raise ValueError(f"{self.db_path}: unsupported compacted graph schema")

        for row in cur.execute("SELECT node_id, ident FROM nodes"):
            ident = str(row["ident"] or "").strip().upper()
            if not ident:
                continue
            self.node_ids_by_ident.setdefault(ident, set()).add(int(row["node_id"]))

        for row in cur.execute("SELECT airway_ident, from_node_id, to_node_id FROM airway_edges"):
            airway = str(row["airway_ident"] or "").strip().upper()
            from_node_id = int(row["from_node_id"])
            to_node_id = int(row["to_node_id"])
            if not airway or from_node_id <= 0 or to_node_id <= 0:
                continue
            airway_map = self.airway_adj.setdefault(airway, {})
            airway_map.setdefault(from_node_id, set()).add(to_node_id)
            nodes = self.airway_nodes.setdefault(airway, set())
            nodes.add(from_node_id)
            nodes.add(to_node_id)

        for row in cur.execute("SELECT from_node_id, to_node_id FROM fra_dct_edges"):
            self.dct_edges.add((int(row["from_node_id"]), int(row["to_node_id"])))

        con.close()

    def has_point(self, ident: str) -> bool:
        return bool(self.node_ids_by_ident.get(ident.strip().upper(), set()))

    def has_airway(self, airway: str) -> bool:
        return airway.strip().upper() in self.airway_adj

    def has_airway_path(self, from_ident: str, airway: str, to_ident: str) -> bool:
        normalized_from = from_ident.strip().upper()
        normalized_airway = airway.strip().upper()
        normalized_to = to_ident.strip().upper()
        cache_key = (normalized_from, normalized_airway, normalized_to)
        cached = self.airway_path_cache.get(cache_key)
        if cached is not None:
            return cached

        start_ids = self.node_ids_by_ident.get(normalized_from, set()) & self.airway_nodes.get(normalized_airway, set())
        target_ids = self.node_ids_by_ident.get(normalized_to, set()) & self.airway_nodes.get(normalized_airway, set())
        if not start_ids or not target_ids:
            self.airway_path_cache[cache_key] = False
            return False

        adjacency = self.airway_adj.get(normalized_airway, {})
        visited = set(start_ids)
        queue = deque(start_ids)
        while queue:
            current = queue.popleft()
            if current in target_ids:
                self.airway_path_cache[cache_key] = True
                return True
            for neighbor in adjacency.get(current, set()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)

        self.airway_path_cache[cache_key] = False
        return False

    def has_exact_dct(self, from_ident: str, to_ident: str) -> bool:
        start_ids = self.node_ids_by_ident.get(from_ident.strip().upper(), set())
        target_ids = self.node_ids_by_ident.get(to_ident.strip().upper(), set())
        if not start_ids or not target_ids:
            return False
        for start_id in start_ids:
            for target_id in target_ids:
                if (start_id, target_id) in self.dct_edges:
                    return True
        return False


class NavdataIndex:
    def __init__(self, db_path: Path, *, airport_aliases: dict[str, str] | None = None) -> None:
        self.db_path = db_path
        self.airports = self._load_values(
            "SELECT DISTINCT airport_identifier FROM tbl_pa_airports WHERE airport_identifier IS NOT NULL AND airport_identifier != ''"
        )
        us_local = self._load_values(
            "SELECT airport_identifier FROM tbl_pa_airports WHERE country = 'UNITED STATES'"
        )
        self.airport_aliases = {f"K{ident}": ident for ident in us_local
                                if len(ident) == 3 and f"K{ident}" not in self.airports}
        for alias, active in (airport_aliases or {}).items():
            if active not in self.airports:
                raise ValueError(f"Airport alias {alias} targets absent airport {active}")
            if alias not in self.airports:
                self.airport_aliases[alias] = active
        self.waypoints = self._load_values(
            "SELECT DISTINCT waypoint_identifier FROM tbl_ea_enroute_waypoints WHERE waypoint_identifier IS NOT NULL AND waypoint_identifier != ''"
        )
        self.terminal_waypoints = self._load_values(
            "SELECT DISTINCT waypoint_identifier FROM tbl_pc_terminal_waypoints WHERE waypoint_identifier IS NOT NULL AND waypoint_identifier != ''"
        )
        self.vhfs = self._load_values(
            "SELECT DISTINCT navaid_identifier FROM tbl_d_vhfnavaids WHERE navaid_identifier IS NOT NULL AND navaid_identifier != ''"
        )
        self.ndbs = self._load_values(
            "SELECT DISTINCT navaid_identifier FROM tbl_db_enroute_ndbnavaids WHERE navaid_identifier IS NOT NULL AND navaid_identifier != ''"
        )
        self.terminal_ndbs = self._load_values(
            "SELECT DISTINCT navaid_identifier FROM tbl_pn_terminal_ndbnavaids WHERE navaid_identifier IS NOT NULL AND navaid_identifier != ''"
        )
        self.star_airports: set[str] = set()
        self.star_waypoints: dict[str, set[str]] = {}
        self._load_star_waypoints()
        self.airway_sequences: dict[str, list[str]] = {}
        self._load_airway_sequences()

    def _load_airway_sequences(self) -> None:
        """Build each airway's published fix list exactly as the game builds it.

        Mirrors RouteDecoder._get_navigraph_airway_names in the game repo: the
        rows are taken in seqno order with no filter on icao_code, so an airway
        split across FIRs concatenates back into one list, and only *consecutive*
        repeats are collapsed.
        """
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                query = (
                    "SELECT route_identifier, waypoint_identifier FROM tbl_er_enroute_airways "
                    "ORDER BY route_identifier, seqno"
                )
                for row in con.execute(query):
                    airway = str(row[0] or "").strip().upper()
                    fix = str(row[1] or "").strip().upper()
                    if not airway or not fix:
                        continue
                    sequence = self.airway_sequences.setdefault(airway, [])
                    if not sequence or sequence[-1] != fix:
                        sequence.append(fix)
        except sqlite3.OperationalError:
            pass  # table absent in mock/older navdata — skip silently

    def _load_star_waypoints(self) -> None:
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                # We only want the FIRST waypoint (minimum seqno) for each procedure
                # transition/route_type group. This defines the valid entry points.
                query = """
                    SELECT airport_identifier, waypoint_identifier
                    FROM (
                        SELECT airport_identifier,
                               waypoint_identifier,
                               ROW_NUMBER() OVER (
                                   PARTITION BY airport_identifier,
                                                procedure_identifier,
                                                COALESCE(transition_identifier, ''),
                                                route_type
                                   ORDER BY seqno
                               ) AS entry_rank
                        FROM tbl_pe_stars
                    )
                    WHERE entry_rank = 1
                """
                for row in con.execute(query):
                    apt = str(row[0] or "").strip().upper()
                    wpt = str(row[1] or "").strip().upper()
                    if apt and wpt:
                        self.star_airports.add(apt)
                        self.star_waypoints.setdefault(apt, set()).add(wpt)
        except sqlite3.OperationalError:
            pass  # table absent in mock/older navdata — skip silently

    def _load_values(self, query: str) -> set[str]:
        try:
            with closing(sqlite3.connect(self.db_path)) as con:
                cur = con.cursor()
                return {
                    str(row[0]).strip().upper()
                    for row in cur.execute(query)
                    if str(row[0] or "").strip()
                }
        except sqlite3.OperationalError:
            return set()

    def has_airport(self, ident: str) -> bool:
        normalized = ident.strip().upper()
        return self.airport_aliases.get(normalized, normalized) in self.airports

    def has_point(self, ident: str) -> bool:
        normalized = ident.strip().upper()
        return (
            normalized in self.waypoints
            or normalized in self.terminal_waypoints
            or normalized in self.vhfs
            or normalized in self.ndbs
            or normalized in self.terminal_ndbs
            or self.has_airport(normalized)
        )

    def has_point_excluding_airports(self, ident: str) -> bool:
        """has_point, minus the airport table — used to tell a route fix apart from
        a bare origin/destination identifier when no compacted graph is supplied."""
        normalized = ident.strip().upper()
        return (
            normalized in self.waypoints
            or normalized in self.terminal_waypoints
            or normalized in self.vhfs
            or normalized in self.ndbs
            or normalized in self.terminal_ndbs
        )

    def has_airway(self, airway: str) -> bool:
        return airway.strip().upper() in self.airway_sequences

    def fix_on_airway(self, fix: str, airway: str) -> bool:
        """Return True when the game could anchor an airway expansion on this fix.

        RouteDecoder._expand_airway_segment slices the airway's fix list between
        the two named fixes, so a hop succeeds exactly when both names appear on
        the airway. Anything stricter than membership rejects routes the game
        flies perfectly well.
        """
        return fix.strip().upper() in self.airway_sequences.get(airway.strip().upper(), ())

    def is_valid_star_entry_point(self, airport: str, fix: str) -> bool:
        """Return True if fix is a published STAR entry point for airport, or if the
        airport has no STAR data (so the check is skipped for airports without procedures)."""
        apt = airport.strip().upper()
        apt = self.airport_aliases.get(apt, apt)
        return apt not in self.star_airports or fix.strip().upper() in self.star_waypoints.get(apt, set())


def load_airport_aliases(path: Path | None, airac: str) -> dict[str, str]:
    """Load reviewed same-site names only for the explicit validation cycle."""
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("airac") != airac:
        raise ValueError("Airport alias manifest does not match validation AIRAC")
    entries = document.get("aliases")
    if not isinstance(entries, dict):
        raise ValueError("Airport alias manifest must contain an aliases object")
    aliases: dict[str, str] = {}
    for alias, entry in entries.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Malformed airport alias: {alias}")
        active = entry.get("active_ident", "")
        distance = entry.get("distance_nm")
        if (not isinstance(alias, str) or len(alias) != 4 or not alias.isalnum()
                or not isinstance(active, str) or len(active) != 4 or not active.isalnum()
                or alias == active or alias != alias.upper() or active != active.upper()
                or entry.get("reason") not in {"same_site_alias", "same_site_rename_candidate"}
                or not isinstance(distance, (int, float)) or isinstance(distance, bool)
                or not math.isfinite(distance) or not 0 <= distance <= 0.01):
            raise ValueError(f"Unproven same-site airport alias: {alias}")
        aliases[alias] = active
    return aliases


def parse_routes_file(routes_path: Path) -> tuple[str, list[RouteRow]]:
    raw_bytes = routes_path.read_bytes()
    text = raw_bytes.decode("utf-8-sig")
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"{routes_path}: file is empty")

    header = lines[0].strip()
    if not header.lower().startswith("airac "):
        raise ValueError(f"{routes_path}: first line must be 'airac <cycle>'")
    airac = header[6:].strip()
    if not airac.isdigit() or len(airac) != 4:
        raise ValueError(f"{routes_path}: invalid AIRAC cycle '{airac}'")

    rows: list[RouteRow] = []
    for line_number, raw_line in enumerate(lines[1:], start=2):
        line = raw_line.rstrip("\r\n")
        if not line.strip() or line.upper().startswith("ORIGIN"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise ValueError(f"{routes_path}:{line_number}: expected at least 3 tab-separated columns")
        route = parts[2].strip().upper()
        if not route:
            continue
        rows.append(
            RouteRow(
                line_number=line_number,
                origin=parts[0].strip().upper(),
                dest=parts[1].strip().upper(),
                route=route,
                creation_airac=parts[3].strip().upper() if len(parts) >= 4 else "",
                author=parts[4].strip() if len(parts) >= 5 else "",
            )
        )
    if not rows:
        raise ValueError(f"{routes_path}: no route rows found")
    return airac, rows


def resolve_graph_db(airac: str, graph_db_arg: str) -> Path | None:
    """Locate the compacted graph, which is optional.

    The graph only backs the FRA DCT warning and the airport-token heuristic;
    navdata is what decides whether a route is accepted. An explicitly requested
    graph that does not exist is still an error.
    """
    if graph_db_arg.strip():
        candidate = Path(graph_db_arg)
        if not candidate.exists():
            raise FileNotFoundError(f"Compacted graph not found: {candidate}")
        return candidate.resolve()
    default = RELATED_ROOT / "Project-Emerald-Upgrade-Routes" / "required" / airac / "compacted_route_graph.s3db"
    return default.resolve() if default.exists() else None


def resolve_navdata_db(airac: str, navdata_db_arg: str) -> Path | None:
    candidates = [Path(navdata_db_arg)] if navdata_db_arg.strip() else [
        RELATED_ROOT / "Project-Emerald-Upgrade-Routes" / "navdata" / f"navigraph_data_{airac}.s3db",
        RELATED_ROOT / "Project-Emerald-Upgrade" / "navdata" / "navigraph_data_default.s3db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def parse_route_tokens(
    row: RouteRow,
    *,
    point_exists: callable,
    airway_exists: callable,
) -> tuple[list[RouteSegment], list[Finding]]:
    findings: list[Finding] = []
    tokens = [token.strip().upper() for token in row.route.split() if token.strip()]
    if len(tokens) < 2:
        findings.append(Finding(row.line_number, "error", "route_too_short", f"{row.origin}->{row.dest}: route must include origin and destination tokens"))
        return [], findings
    if tokens[0] != row.origin:
        findings.append(Finding(row.line_number, "error", "origin_mismatch", f"{row.origin}->{row.dest}: route starts with {tokens[0]}, expected {row.origin}"))
    if tokens[-1] != row.dest:
        findings.append(Finding(row.line_number, "error", "dest_mismatch", f"{row.origin}->{row.dest}: route ends with {tokens[-1]}, expected {row.dest}"))

    interior = tokens[1:-1]
    if not interior:
        return [], findings

    current_token = row.origin
    segments: list[RouteSegment] = []
    index = 0
    while index < len(interior):
        token = interior[index]
        next_token = interior[index + 1] if index + 1 < len(interior) else ""

        # 72 idents in AIRAC 2608 are both an airway and a fix (A1, T5, UN601 ...).
        # For those, keep disambiguating on what follows; an unambiguous airway is
        # a connector whatever comes next, so an unknown fix after it is blamed on
        # the fix rather than on the airway.
        is_connector = token == "DCT" or (
            airway_exists(token)
            and (not point_exists(token) or (next_token != "" and point_exists(next_token)))
        )
        if is_connector:
            if index == len(interior) - 1:
                segments.append(RouteSegment(current_token, token, row.dest))
                current_token = row.dest
                index += 1
                continue
            segments.append(RouteSegment(current_token, token, next_token))
            current_token = next_token
            index += 2
            continue

        # Anything else is a fix. An unrecognised one is reported once, by name, by
        # the point_missing check in validate_routes; parsing continues so the rest
        # of the route is still inspected instead of being abandoned here.
        segments.append(RouteSegment(current_token, "", token))
        current_token = token
        index += 1

    if current_token != row.dest:
        segments.append(RouteSegment(current_token, "", row.dest))
    return segments, findings


def validate_routes(
    routes_path: Path,
    graph_db: Path | None,
    navdata_db: Path | None,
    *,
    strict_dct: bool,
    max_findings: int,
    airport_aliases: dict[str, str] | None = None,
) -> ValidationSummary:
    """Validate contributed routes the way the game resolves them.

    Navdata is the authority: the game expands a contributed route by name against
    tbl_er_enroute_airways, never against the compacted graph, which exists for
    route *generation* and deliberately drops pass-through fixes and coordinate
    points. The graph is consulted only where navdata cannot answer — the FRA DCT
    warning — and as a fallback when no navdata is supplied.
    """
    airac, rows = parse_routes_file(routes_path)
    graph = GraphIndex(graph_db) if graph_db else None
    navdata = NavdataIndex(navdata_db, airport_aliases=airport_aliases) if navdata_db else None
    # Navdata answers airway questions only when it actually carries the airway
    # table; a navdata file without it must not deprecate every airway hop.
    airway_source = navdata if navdata and navdata.airway_sequences else None
    errors: list[Finding] = []
    warnings: list[Finding] = []

    def point_exists(token: str) -> bool:
        normalized = token.strip().upper()
        if COORDINATE_FIX_RE.match(normalized):
            return True
        if navdata and navdata.has_point(normalized):
            return True
        return bool(graph and graph.has_point(normalized))

    def airway_exists(token: str) -> bool:
        normalized = token.strip().upper()
        if airway_source:
            return airway_source.has_airway(normalized)
        return bool(graph and graph.has_airway(normalized))

    def is_airport_token(row: RouteRow, token: str) -> bool:
        if token not in {row.origin, row.dest}:
            return False
        if graph:
            return not graph.has_point(token)
        return not (navdata and navdata.has_point_excluding_airports(token))

    for row in rows:
        segments, parse_findings = parse_route_tokens(row, point_exists=point_exists, airway_exists=airway_exists)
        for finding in parse_findings:
            target = errors if finding.severity == "error" else warnings
            target.append(finding)
        if len(errors) >= max_findings:
            break
        if not segments:
            continue

        if navdata and not navdata.has_airport(row.origin):
            errors.append(Finding(row.line_number, "error", "origin_missing", f"{row.origin}->{row.dest}: origin airport {row.origin} missing from navdata"))
        if navdata and not navdata.has_airport(row.dest):
            errors.append(Finding(row.line_number, "error", "dest_missing", f"{row.origin}->{row.dest}: destination airport {row.dest} missing from navdata"))

        point_idents = [
            token
            for segment in segments
            for token in (segment.from_token, segment.to_token)
            if token not in {row.origin, row.dest}
        ]
        for point_ident in sorted(set(point_idents)):
            if point_exists(point_ident):
                continue
            errors.append(Finding(row.line_number, "error", "point_missing", f"{row.origin}->{row.dest}: point {point_ident} missing from navdata"))
            if len(errors) >= max_findings:
                break
        if len(errors) >= max_findings:
            break

        for segment in segments:
            from_point = segment.from_token
            connector = segment.connector
            to_point = segment.to_token
            from_is_airport = is_airport_token(row, from_point)
            to_is_airport = is_airport_token(row, to_point)

            if not connector:
                if not from_is_airport and not to_is_airport:
                    warnings.append(Finding(row.line_number, "warning", "implicit_direct", f"{row.origin}->{row.dest}: implicit direct segment {from_point}->{to_point}"))
                continue

            if connector == "DCT":
                if from_is_airport or to_is_airport:
                    continue
                # An endpoint point_missing already rejected cannot be looked up here.
                if not point_exists(from_point) or not point_exists(to_point):
                    continue
                if graph and graph.has_exact_dct(from_point, to_point):
                    continue
                detail = f"{row.origin}->{row.dest}: DCT {from_point}->{to_point} not present in FRA DCT graph"
                target = errors if strict_dct else warnings
                code = "dct_not_in_graph" if strict_dct else "dct_unchecked"
                target.append(Finding(row.line_number, "error" if strict_dct else "warning", code, detail))
                if len(errors) >= max_findings:
                    break
                continue

            if from_is_airport or to_is_airport:
                errors.append(Finding(row.line_number, "error", "airway_to_airport", f"{row.origin}->{row.dest}: airway {connector} cannot connect directly to airport token"))
                if len(errors) >= max_findings:
                    break
                continue
            if not airway_exists(connector):
                errors.append(Finding(row.line_number, "error", "airway_missing", f"{row.origin}->{row.dest}: airway {connector} missing from navdata"))
                if len(errors) >= max_findings:
                    break
                continue
            # Check each endpoint against the airway separately, so a hop whose
            # other end is an unknown fix still reports what it can. An endpoint
            # point_missing already rejected is skipped — "X is not on this
            # airway" says nothing useful about a fix that does not exist.
            if airway_source:
                off_airway = [
                    fix
                    for fix in dict.fromkeys((from_point, to_point))
                    if point_exists(fix) and not airway_source.fix_on_airway(fix, connector)
                ]
                if off_airway:
                    errors.append(Finding(row.line_number, "error", "airway_disconnect", f"{row.origin}->{row.dest}: {' and '.join(off_airway)} not on airway {connector}"))
                    if len(errors) >= max_findings:
                        break
            elif graph and not graph.has_airway_path(from_point, connector, to_point):
                errors.append(Finding(row.line_number, "error", "airway_disconnect", f"{row.origin}->{row.dest}: no {connector} path from {from_point} to {to_point}"))
                if len(errors) >= max_findings:
                    break

        # STAR entry membership check — requires navdata with tbl_pe_stars
        if navdata and navdata.star_airports:
            last_fix = ""
            for segment in reversed(segments):
                if segment.to_token != row.dest:
                    continue
                candidate = segment.from_token
                if candidate not in {row.origin, row.dest}:
                    last_fix = candidate
                break
            if last_fix:
                if not navdata.is_valid_star_entry_point(row.dest, last_fix):
                    errors.append(Finding(
                        row.line_number, "error", "star_entry_not_in_procedure",
                        f"{row.origin}->{row.dest}: last fix '{last_fix}' is not a published "
                        f"STAR entry point for {row.dest} — possible proximity substitution",
                    ))

        if len(errors) >= max_findings:
            break

    return ValidationSummary(
        airac=airac,
        routes_checked=len(rows),
        errors=tuple(errors),
        warnings=tuple(warnings),
        graph_db=graph_db,
        navdata_db=navdata_db,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate community routes against the AIRAC navigation database.",
    )
    parser.add_argument("--routes-path", default=str(DEFAULT_ROUTES_PATH), help="Path to ROUTES/routes.tsv")
    parser.add_argument("--graph-db", default="", help="Optional path to compacted_route_graph.s3db (FRA DCT warnings only)")
    parser.add_argument("--navdata-db", default="", help="Path to navigraph_data.s3db — decides route acceptance")
    parser.add_argument("--airport-aliases", type=Path, help="Reviewed same-site aliases for this AIRAC")
    parser.add_argument("--strict-dct", action="store_true", help="Fail DCT segments not present in FRA DCT graph")
    parser.add_argument("--max-findings", type=int, default=50, help="Stop after this many errors")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    routes_path = Path(args.routes_path).resolve()

    try:
        airac, _ = parse_routes_file(routes_path)
        graph_db = resolve_graph_db(airac, args.graph_db)
        navdata_db = resolve_navdata_db(airac, args.navdata_db)
        if navdata_db is None:
            raise FileNotFoundError(
                f"Unable to find navdata for AIRAC {airac}; pass --navdata-db. "
                "Route acceptance is decided against tbl_er_enroute_airways, not the compacted graph."
            )
        summary = validate_routes(
            routes_path,
            graph_db,
            navdata_db,
            strict_dct=bool(args.strict_dct),
            max_findings=max(1, int(args.max_findings)),
            airport_aliases=load_airport_aliases(args.airport_aliases, airac),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    status = "PASS" if summary.is_valid else "FAIL"
    print(f"{status} {routes_path}")
    print(f"AIRAC: {summary.airac}")
    print(f"Graph DB: {summary.graph_db if summary.graph_db else 'not used'}")
    print(f"Navdata DB: {summary.navdata_db}")
    print(f"Routes checked: {summary.routes_checked}")
    print(f"Errors: {len(summary.errors)}")
    print(f"Warnings: {len(summary.warnings)}")

    for finding in summary.errors:
        print(f"ERROR line {finding.line_number} [{finding.code}] {finding.detail}")
    for finding in summary.warnings[:20]:
        print(f"WARN line {finding.line_number} [{finding.code}] {finding.detail}")

    return 0 if summary.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
