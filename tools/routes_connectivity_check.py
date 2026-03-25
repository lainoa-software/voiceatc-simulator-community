#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROUTES_PATH = ROOT / "ROUTES" / "routes.tsv"
RELATED_ROOT = ROOT.parent
GRAPH_SCHEMA_VERSION = "7"


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
    graph_db: Path
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
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.airports = self._load_values(
            "SELECT DISTINCT airport_identifier FROM tbl_pa_airports WHERE airport_identifier IS NOT NULL AND airport_identifier != ''"
        )
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

    def _load_star_waypoints(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as con:
                # We only want the FIRST waypoint (minimum seqno) for each procedure
                # transition/route_type group. This defines the valid entry points.
                query = """
                    SELECT airport_identifier, waypoint_identifier
                    FROM tbl_pe_stars
                    WHERE (airport_identifier, procedure_identifier, transition_identifier, route_type, seqno) IN (
                        SELECT airport_identifier, procedure_identifier, transition_identifier, route_type, MIN(seqno)
                        FROM tbl_pe_stars
                        GROUP BY airport_identifier, procedure_identifier, transition_identifier, route_type
                    )
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
            with sqlite3.connect(self.db_path) as con:
                cur = con.cursor()
                return {
                    str(row[0]).strip().upper()
                    for row in cur.execute(query)
                    if str(row[0] or "").strip()
                }
        except sqlite3.OperationalError:
            return set()

    def has_airport(self, ident: str) -> bool:
        return ident.strip().upper() in self.airports

    def has_point(self, ident: str) -> bool:
        normalized = ident.strip().upper()
        return (
            normalized in self.waypoints
            or normalized in self.terminal_waypoints
            or normalized in self.vhfs
            or normalized in self.ndbs
            or normalized in self.terminal_ndbs
            or normalized in self.airports
        )

    def is_valid_star_entry_point(self, airport: str, fix: str) -> bool:
        """Return True if fix is a published STAR entry point for airport, or if the
        airport has no STAR data (so the check is skipped for airports without procedures)."""
        apt = airport.strip().upper()
        return apt not in self.star_airports or fix.strip().upper() in self.star_waypoints.get(apt, set())


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


def resolve_graph_db(airac: str, graph_db_arg: str) -> Path:
    candidates = [Path(graph_db_arg)] if graph_db_arg.strip() else [
        RELATED_ROOT / "Project-Emerald-Upgrade-Routes" / "required" / airac / "compacted_route_graph.s3db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    candidate_list = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Unable to find compacted graph for AIRAC {airac}. Checked: {candidate_list}")


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

        if token == "DCT" or (airway_exists(token) and next_token and point_exists(next_token)):
            if index == len(interior) - 1:
                segments.append(RouteSegment(current_token, token, row.dest))
                current_token = row.dest
                index += 1
                continue
            if not next_token or not point_exists(next_token):
                findings.append(Finding(row.line_number, "error", "route_token_pattern", f"{row.origin}->{row.dest}: connector {token} is not followed by a known point"))
                return segments, findings
            segments.append(RouteSegment(current_token, token, next_token))
            current_token = next_token
            index += 2
            continue

        if point_exists(token):
            segments.append(RouteSegment(current_token, "", token))
            current_token = token
            index += 1
            continue

        findings.append(Finding(row.line_number, "error", "token_unknown", f"{row.origin}->{row.dest}: token {token} is neither a known point nor airway"))
        return segments, findings

    if current_token != row.dest:
        segments.append(RouteSegment(current_token, "", row.dest))
    return segments, findings


def validate_routes(
    routes_path: Path,
    graph_db: Path,
    navdata_db: Path | None,
    *,
    strict_dct: bool,
    max_findings: int,
) -> ValidationSummary:
    airac, rows = parse_routes_file(routes_path)
    graph = GraphIndex(graph_db)
    navdata = NavdataIndex(navdata_db) if navdata_db else None
    errors: list[Finding] = []
    warnings: list[Finding] = []

    def point_exists(token: str) -> bool:
        normalized = token.strip().upper()
        return graph.has_point(normalized) or bool(navdata and navdata.has_point(normalized))

    def airway_exists(token: str) -> bool:
        return graph.has_airway(token.strip().upper())

    for row in rows:
        segments, parse_findings = parse_route_tokens(row, point_exists=point_exists, airway_exists=airway_exists)
        for finding in parse_findings:
            target = errors if finding.severity == "error" else warnings
            target.append(finding)
        if any(finding.severity == "error" for finding in parse_findings):
            if len(errors) >= max_findings:
                break
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
            if graph.has_point(point_ident):
                continue
            if navdata and navdata.has_point(point_ident):
                continue
            errors.append(Finding(row.line_number, "error", "point_missing", f"{row.origin}->{row.dest}: point {point_ident} missing from graph/navdata"))
            if len(errors) >= max_findings:
                break
        if len(errors) >= max_findings:
            break

        for segment in segments:
            from_point = segment.from_token
            connector = segment.connector
            to_point = segment.to_token
            from_is_airport = from_point in {row.origin, row.dest} and not graph.has_point(from_point)
            to_is_airport = to_point in {row.origin, row.dest} and not graph.has_point(to_point)

            if not connector:
                if not from_is_airport and not to_is_airport:
                    warnings.append(Finding(row.line_number, "warning", "implicit_direct", f"{row.origin}->{row.dest}: implicit direct segment {from_point}->{to_point}"))
                continue

            if connector == "DCT":
                if from_is_airport or to_is_airport:
                    continue
                if graph.has_exact_dct(from_point, to_point):
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
            if not graph.has_airway(connector):
                errors.append(Finding(row.line_number, "error", "airway_missing", f"{row.origin}->{row.dest}: airway {connector} missing from compacted graph"))
                if len(errors) >= max_findings:
                    break
                continue
            if not graph.has_airway_path(from_point, connector, to_point):
                errors.append(Finding(row.line_number, "error", "airway_disconnect", f"{row.origin}->{row.dest}: no {connector} path from {from_point} to {to_point}"))
                if len(errors) >= max_findings:
                    break

        # STAR entry membership check — requires navdata with tbl_pe_stars
        if navdata and navdata.star_airports:
            tokens = [t.strip().upper() for t in row.route.split() if t.strip()]
            if len(tokens) >= 3:
                last_fix = tokens[-2]
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
        description="Validate community routes against the AIRAC compacted route graph.",
    )
    parser.add_argument("--routes-path", default=str(DEFAULT_ROUTES_PATH), help="Path to ROUTES/routes.tsv")
    parser.add_argument("--graph-db", default="", help="Path to compacted_route_graph.s3db")
    parser.add_argument("--navdata-db", default="", help="Optional path to navigraph_data.s3db for airport/point lookup")
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
        summary = validate_routes(
            routes_path,
            graph_db,
            navdata_db,
            strict_dct=bool(args.strict_dct),
            max_findings=max(1, int(args.max_findings)),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    status = "PASS" if summary.is_valid else "FAIL"
    print(f"{status} {routes_path}")
    print(f"AIRAC: {summary.airac}")
    print(f"Graph DB: {summary.graph_db}")
    print(f"Navdata DB: {summary.navdata_db if summary.navdata_db else 'not used'}")
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
