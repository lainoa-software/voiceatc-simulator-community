#!/usr/bin/env python3
"""
routes_airac_migration.py — AIRAC route compliance migration tool.

For each route in ROUTES/routes.tsv, checks connectivity against a new AIRAC's
compacted graph.  Produces three outputs:

  migration_ready.tsv   — same as source but with failing LainoaSoftware routes
                          blanked (empty route column) so route_builder.py can
                          rebuild them as "blank pairs".
  migration_report.json — machine-readable summary for the CI workflow.
  migration_report.md   — human-readable PR body (optional).

Only routes authored by LainoaSoftware (or with no author) are auto-blanked.
Community-authored routes are flagged in the report but never modified.

Usage:
  python tools/routes_airac_migration.py \\
    --routes        ROUTES/routes.tsv \\
    --graph         /path/to/compacted_route_graph_XXXX.s3db \\
    --navdata       /path/to/navigraph_data.s3db \\
    --target-airac  XXXX \\
    --output-tsv    /tmp/migration_ready.tsv \\
    --report-json   /tmp/migration_report.json \\
    --report-md     /tmp/migration_report.md
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Ensure tools/ directory is on sys.path so sibling imports work
# ---------------------------------------------------------------------------
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from routes_connectivity_check import (  # noqa: E402
    Finding,
    GraphIndex,
    NavdataIndex,
    RouteRow,
    RouteSegment,
    parse_routes_file,
    parse_route_tokens,
)

# ---------------------------------------------------------------------------
# AIRAC guard constant
# ---------------------------------------------------------------------------
_PROTECTED_AIRAC_MAX = 2403  # inclusive — 2403 is the bundled default


# ---------------------------------------------------------------------------
# Per-route outcome
# ---------------------------------------------------------------------------

@dataclass
class RouteOutcome:
    row: RouteRow
    errors: list[Finding]
    warnings: list[Finding]
    category: str  # "ok" | "lainoa_rebuild" | "community_flag"


def _is_lainoa(author: str) -> bool:
    return author.strip() in ("LainoaSoftware", "")


# ---------------------------------------------------------------------------
# Core validation — mirrors validate_routes() but without max_findings cap
# ---------------------------------------------------------------------------

def _validate_row(
    row: RouteRow,
    graph: GraphIndex,
    navdata: Optional[NavdataIndex],
    *,
    strict_dct: bool,
) -> tuple[list[Finding], list[Finding]]:
    """Return (errors, warnings) for a single route row."""
    errors: list[Finding] = []
    warnings: list[Finding] = []

    def point_exists(token: str) -> bool:
        normalized = token.strip().upper()
        return graph.has_point(normalized) or bool(navdata and navdata.has_point(normalized))

    def airway_exists(token: str) -> bool:
        return graph.has_airway(token.strip().upper())

    segments, parse_findings = parse_route_tokens(
        row, point_exists=point_exists, airway_exists=airway_exists
    )
    for finding in parse_findings:
        (errors if finding.severity == "error" else warnings).append(finding)

    # If route couldn't even be parsed, no point checking further
    if any(f.severity == "error" for f in parse_findings):
        return errors, warnings

    # Airport existence (requires navdata)
    if navdata:
        if not navdata.has_airport(row.origin):
            errors.append(Finding(
                row.line_number, "error", "origin_missing",
                f"{row.origin}->{row.dest}: origin airport {row.origin} missing from navdata",
            ))
        if not navdata.has_airport(row.dest):
            errors.append(Finding(
                row.line_number, "error", "dest_missing",
                f"{row.origin}->{row.dest}: destination airport {row.dest} missing from navdata",
            ))

    # Interior point existence
    interior_points: set[str] = set()
    for segment in segments:
        for token in (segment.from_token, segment.to_token):
            if token not in {row.origin, row.dest}:
                interior_points.add(token)
    for point_ident in sorted(interior_points):
        if not point_exists(point_ident):
            errors.append(Finding(
                row.line_number, "error", "point_missing",
                f"{row.origin}->{row.dest}: point {point_ident} missing from graph/navdata",
            ))

    # Segment connectivity
    for segment in segments:
        from_point = segment.from_token
        connector = segment.connector
        to_point = segment.to_token

        from_is_airport = from_point in {row.origin, row.dest} and not graph.has_point(from_point)
        to_is_airport = to_point in {row.origin, row.dest} and not graph.has_point(to_point)

        if not connector:
            if not from_is_airport and not to_is_airport:
                warnings.append(Finding(
                    row.line_number, "warning", "implicit_direct",
                    f"{row.origin}->{row.dest}: implicit direct segment {from_point}->{to_point}",
                ))
            continue

        if connector == "DCT":
            if from_is_airport or to_is_airport:
                continue
            if graph.has_exact_dct(from_point, to_point):
                continue
            detail = f"{row.origin}->{row.dest}: DCT {from_point}->{to_point} not present in FRA DCT graph"
            if strict_dct:
                errors.append(Finding(row.line_number, "error", "dct_not_in_graph", detail))
            else:
                warnings.append(Finding(row.line_number, "warning", "dct_unchecked", detail))
            continue

        if from_is_airport or to_is_airport:
            errors.append(Finding(
                row.line_number, "error", "airway_to_airport",
                f"{row.origin}->{row.dest}: airway {connector} cannot connect directly to airport token",
            ))
            continue

        if not graph.has_airway(connector):
            errors.append(Finding(
                row.line_number, "error", "airway_missing",
                f"{row.origin}->{row.dest}: airway {connector} missing from compacted graph",
            ))
            continue

        if not graph.has_airway_path(from_point, connector, to_point):
            errors.append(Finding(
                row.line_number, "error", "airway_disconnect",
                f"{row.origin}->{row.dest}: no {connector} path from {from_point} to {to_point}",
            ))

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

    return errors, warnings


# ---------------------------------------------------------------------------
# TSV reconstruction helpers
# ---------------------------------------------------------------------------

def _read_raw_lines(routes_path: Path) -> list[str]:
    """Read all lines preserving exact content (including blanks)."""
    text = routes_path.read_bytes().decode("utf-8-sig")
    return text.splitlines(keepends=True)


def _write_migration_tsv(
    output_path: Path,
    source_lines: list[str],
    target_airac: str,
    blank_keys: set[tuple[str, str]],
) -> None:
    """
    Write migration_ready.tsv.

    - Header line changed to `airac <target_airac>`.
    - Rows whose (origin, dest) is in blank_keys get their route column cleared.
    - All other rows written verbatim.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        for i, raw_line in enumerate(source_lines):
            line = raw_line.rstrip("\r\n")

            # First line: replace AIRAC header
            if i == 0:
                fh.write(f"airac {target_airac}\n")
                continue

            # Column-name header row — write verbatim
            if line.upper().startswith("ORIGIN\t"):
                fh.write(raw_line if raw_line.endswith(("\n", "\r")) else raw_line + "\n")
                continue

            # Empty or whitespace-only lines — preserve
            if not line.strip():
                fh.write(raw_line if raw_line.endswith(("\n", "\r")) else raw_line + "\n")
                continue

            parts = line.split("\t")
            if len(parts) < 2:
                fh.write(raw_line if raw_line.endswith(("\n", "\r")) else raw_line + "\n")
                continue

            origin = parts[0].strip().upper()
            dest = parts[1].strip().upper()

            if (origin, dest) in blank_keys:
                # Blank the route / creation_airac / author columns
                fh.write(f"{origin}\t{dest}\t\t\t\n")
            else:
                fh.write(raw_line if raw_line.endswith(("\n", "\r")) else raw_line + "\n")


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _build_json_report(
    target_airac: str,
    source_airac: str,
    graph_path: Path,
    navdata_path: Optional[Path],
    outcomes: list[RouteOutcome],
) -> dict:
    lainoa_list = []
    community_list = []
    ok_count = 0

    for outcome in outcomes:
        if outcome.category == "ok":
            ok_count += 1
        elif outcome.category == "lainoa_rebuild":
            lainoa_list.append({
                "line_number": outcome.row.line_number,
                "origin": outcome.row.origin,
                "dest": outcome.row.dest,
                "old_route": outcome.row.route,
                "errors": [{"code": f.code, "detail": f.detail} for f in outcome.errors],
            })
        else:  # community_flag
            community_list.append({
                "line_number": outcome.row.line_number,
                "origin": outcome.row.origin,
                "dest": outcome.row.dest,
                "author": outcome.row.author,
                "old_route": outcome.row.route,
                "creation_airac": outcome.row.creation_airac,
                "errors": [{"code": f.code, "detail": f.detail} for f in outcome.errors],
            })

    return {
        "schema_version": 1,
        "target_airac": target_airac,
        "source_airac": source_airac,
        "generated_at_utc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "graph_db": str(graph_path),
        "navdata_db": str(navdata_path) if navdata_path else None,
        "summary": {
            "total_routes_checked": len(outcomes),
            "routes_ok": ok_count,
            "lainoa_routes_to_rebuild": len(lainoa_list),
            "community_routes_needing_review": len(community_list),
        },
        "lainoa_routes_to_rebuild": lainoa_list,
        "community_routes_needing_review": community_list,
    }


def _build_md_report(report: dict, max_community_display: int = 50) -> str:
    s = report["summary"]
    target = report["target_airac"]
    source = report["source_airac"]

    lines: list[str] = [
        f"## AIRAC {target} Route Compliance Migration",
        "",
        f"| | |",
        f"|---|---|",
        f"| **Source AIRAC** | {source} |",
        f"| **Target AIRAC** | {target} |",
        f"| **Routes checked** | {s['total_routes_checked']:,} |",
        f"| **Routes OK** | {s['routes_ok']:,} |",
        f"| **LainoaSoftware routes rebuilt** | {s['lainoa_routes_to_rebuild']:,} |",
        f"| **Community routes needing review** | {s['community_routes_needing_review']:,} |",
        "",
        "---",
        "",
        "### What Changed",
        "",
        f"- The file header has been bumped to `airac {target}`.",
    ]

    n_rebuilt = s["lainoa_routes_to_rebuild"]
    if n_rebuilt > 0:
        lines.append(
            f"- **{n_rebuilt:,}** LainoaSoftware-authored routes were found invalid against the "
            f"new AIRAC {target} graph and have been automatically rebuilt using `route_builder.py`."
        )
        lines.append(f"  Their `CREATION_AIRAC` has been updated to `{target}`.")
    else:
        lines.append("- No LainoaSoftware routes required rebuilding.")

    lines.append("")

    community_list = report.get("community_routes_needing_review", [])
    if community_list:
        lines += [
            "---",
            "",
            "### Community Routes Requiring Human Review",
            "",
            "These routes were submitted by community contributors and have **not** been "
            "automatically changed. They must be reviewed and manually corrected.",
            "",
            "| Line | Origin | Dest | Author | Errors |",
            "|------|--------|------|--------|--------|",
        ]
        for entry in community_list[:max_community_display]:
            error_summary = "; ".join(e["code"] for e in entry["errors"])
            author = entry.get("author") or "—"
            lines.append(
                f"| {entry['line_number']} | {entry['origin']} | {entry['dest']} "
                f"| {author} | {error_summary} |"
            )
        if len(community_list) > max_community_display:
            lines.append(
                f"\n> … and {len(community_list) - max_community_display} more (see `migration_report.json`)."
            )
        lines.append("")
        lines += [
            "> **Note:** The rows above still contain their original routes.",
            "> They will fail the connectivity check until corrected by their authors.",
            "",
        ]
    else:
        lines += [
            "---",
            "",
            "No community-authored routes require review.",
            "",
        ]

    lines.append("---")
    lines.append("")
    lines.append("*Auto-generated by `routes_airac_migration.py` + `route_builder.py`*")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check AIRAC route compliance and produce a migration-ready TSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--routes", required=True, metavar="PATH",
                        help="Path to ROUTES/routes.tsv")
    parser.add_argument("--graph", required=True, metavar="PATH",
                        help="Path to compacted_route_graph_XXXX.s3db")
    parser.add_argument("--navdata", metavar="PATH", default="",
                        help="Path to navigraph_data.s3db (optional)")
    parser.add_argument("--target-airac", required=True, metavar="XXXX",
                        help="New AIRAC cycle to migrate to (4-digit)")
    parser.add_argument("--output-tsv", required=True, metavar="PATH",
                        help="Where to write migration_ready.tsv")
    parser.add_argument("--report-json", required=True, metavar="PATH",
                        help="Where to write migration_report.json")
    parser.add_argument("--report-md", metavar="PATH", default="",
                        help="Where to write migration_report.md (optional)")
    parser.add_argument("--strict-dct", action="store_true",
                        help="Treat DCT segments not in FRA graph as errors")
    parser.add_argument("--max-community-display", type=int, default=50, metavar="N",
                        help="Max community route errors to show in markdown report")
    args = parser.parse_args()

    target_airac = args.target_airac.strip()

    # -----------------------------------------------------------------------
    # Hard guard: never modify routes for AIRAC 2403 or older
    # -----------------------------------------------------------------------
    if not target_airac.isdigit() or len(target_airac) != 4:
        print(f"ERROR: --target-airac must be a 4-digit AIRAC cycle, got: {target_airac!r}",
              file=sys.stderr)
        return 1
    if int(target_airac) <= _PROTECTED_AIRAC_MAX:
        print(
            f"ERROR: target AIRAC {target_airac} is <= {_PROTECTED_AIRAC_MAX}. "
            f"AIRAC {_PROTECTED_AIRAC_MAX} is the bundled default for users without a "
            "Navigraph subscription and must never be modified by this pipeline.",
            file=sys.stderr,
        )
        return 1

    routes_path = Path(args.routes).resolve()
    graph_path = Path(args.graph).resolve()
    navdata_path = Path(args.navdata).resolve() if args.navdata.strip() else None
    output_tsv = Path(args.output_tsv)
    report_json_path = Path(args.report_json)
    report_md_path = Path(args.report_md) if args.report_md.strip() else None

    # -----------------------------------------------------------------------
    # Validate inputs
    # -----------------------------------------------------------------------
    for label, path in [("routes", routes_path), ("graph", graph_path)]:
        if not path.exists():
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 1
    if navdata_path and not navdata_path.exists():
        print(f"WARNING: navdata file not found, proceeding without it: {navdata_path}",
              file=sys.stderr)
        navdata_path = None

    # -----------------------------------------------------------------------
    # Load indexes
    # -----------------------------------------------------------------------
    print(f"Loading graph index: {graph_path}")
    try:
        graph = GraphIndex(graph_path)
    except Exception as exc:
        print(f"ERROR loading graph: {exc}", file=sys.stderr)
        return 1

    navdata: Optional[NavdataIndex] = None
    if navdata_path:
        print(f"Loading navdata index: {navdata_path}")
        try:
            navdata = NavdataIndex(navdata_path)
        except Exception as exc:
            print(f"WARNING: could not load navdata ({exc}), proceeding without it",
                  file=sys.stderr)

    # -----------------------------------------------------------------------
    # Parse routes
    # -----------------------------------------------------------------------
    print(f"Parsing routes: {routes_path}")
    try:
        source_airac, rows = parse_routes_file(routes_path)
    except Exception as exc:
        print(f"ERROR parsing routes: {exc}", file=sys.stderr)
        return 1
    print(f"  Source AIRAC: {source_airac}  |  Routes: {len(rows):,}")

    # -----------------------------------------------------------------------
    # Validate every non-blank route
    # -----------------------------------------------------------------------
    print(f"Validating {len(rows):,} routes against AIRAC {target_airac} graph…")
    outcomes: list[RouteOutcome] = []
    for i, row in enumerate(rows, 1):
        if i % 10000 == 0 or i == len(rows):
            print(f"  {i:,}/{len(rows):,}", flush=True)
        errors, warnings = _validate_row(
            row, graph, navdata, strict_dct=args.strict_dct
        )
        if errors:
            category = "lainoa_rebuild" if _is_lainoa(row.author) else "community_flag"
        else:
            category = "ok"
        outcomes.append(RouteOutcome(row=row, errors=errors, warnings=warnings, category=category))

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    lainoa_count = sum(1 for o in outcomes if o.category == "lainoa_rebuild")
    community_count = sum(1 for o in outcomes if o.category == "community_flag")
    ok_count = sum(1 for o in outcomes if o.category == "ok")
    print(f"\nResults:")
    print(f"  OK:                          {ok_count:,}")
    print(f"  LainoaSoftware to rebuild:   {lainoa_count:,}")
    print(f"  Community routes to review:  {community_count:,}")

    # -----------------------------------------------------------------------
    # Build blank-keys set for migration TSV
    # -----------------------------------------------------------------------
    blank_keys: set[tuple[str, str]] = {
        (o.row.origin, o.row.dest)
        for o in outcomes
        if o.category == "lainoa_rebuild"
    }

    # -----------------------------------------------------------------------
    # Write migration_ready.tsv
    # -----------------------------------------------------------------------
    print(f"\nWriting migration_ready.tsv: {output_tsv}")
    try:
        source_lines = _read_raw_lines(routes_path)
        _write_migration_tsv(output_tsv, source_lines, target_airac, blank_keys)
    except Exception as exc:
        print(f"ERROR writing migration TSV: {exc}", file=sys.stderr)
        return 1

    # -----------------------------------------------------------------------
    # Write reports
    # -----------------------------------------------------------------------
    report = _build_json_report(
        target_airac, source_airac, graph_path, navdata_path, outcomes
    )
    try:
        report_json_path.parent.mkdir(parents=True, exist_ok=True)
        report_json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Written: {report_json_path}")
    except Exception as exc:
        print(f"ERROR writing JSON report: {exc}", file=sys.stderr)
        return 1

    if report_md_path:
        try:
            md_text = _build_md_report(report, max_community_display=args.max_community_display)
            report_md_path.parent.mkdir(parents=True, exist_ok=True)
            report_md_path.write_text(md_text, encoding="utf-8")
            print(f"Written: {report_md_path}")
        except Exception as exc:
            print(f"ERROR writing markdown report: {exc}", file=sys.stderr)
            return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
