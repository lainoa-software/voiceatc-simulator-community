#!/usr/bin/env python3
"""
routes_airac_migration.py — AIRAC route compliance migration tool.

For each route in ROUTES/routes.tsv, checks connectivity against a new AIRAC's
navigation database, using routes_connectivity_check.validate_routes so this
tool and the contribution gate always agree on what "flyable" means.  Navdata
is therefore required: the compacted graph is built for route *generation* and
drops the pass-through fixes, oceanic coordinate points and cross-FIR airway
halves that named routes rely on, so it cannot decide acceptance for a tool
that blanks rows.  Produces three outputs:

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

# ---------------------------------------------------------------------------
# Ensure tools/ directory is on sys.path so sibling imports work
# ---------------------------------------------------------------------------
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from routes_connectivity_check import (  # noqa: E402
    Finding,
    RouteRow,
    parse_routes_file,
    validate_routes,
    load_airport_aliases,
)

# ---------------------------------------------------------------------------
# AIRAC guard constant
# ---------------------------------------------------------------------------
_PROTECTED_AIRAC_MAX = 2503  # inclusive — 2503 is the bundled default


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
# Core validation — delegated wholesale to the contribution gate
# ---------------------------------------------------------------------------

def _validate_rows(
    routes_path: Path,
    rows: list[RouteRow],
    graph_db: Path | None,
    navdata_db: Path,
    *,
    strict_dct: bool,
    airport_aliases: dict[str, str] | None = None,
) -> list[RouteOutcome]:
    """Categorise every route row using the shared connectivity checker.

    routes_connectivity_check.validate_routes is the single implementation of
    "would the game fly this route", so this tool calls it rather than keeping a
    second copy that can drift.  The copy it used to keep resolved hops through
    the compacted graph, which rejects any route naming a fix the graph bake
    collapsed, an oceanic lat/lon point the graph does not hold, or an airway
    Navigraph splits across FIRs — and it read the last fix off the raw token
    list, so every route ending "... DCT <dest>" failed the STAR entry check on
    the literal token DCT.  Against AIRAC 2608 that pair of faults marked 73,941
    of 99,869 routes for rebuild where the shared checker marks 3,904.

    validate_routes walks the file itself, so its findings are grouped back onto
    rows by line number, which parse_routes_file assigns uniquely.
    """
    summary = validate_routes(
        routes_path,
        graph_db,
        navdata_db,
        strict_dct=strict_dct,
        # Migration has to see every route: a findings cap stops the scan early
        # and would silently categorise the untouched tail as "ok".
        max_findings=sys.maxsize,
        airport_aliases=airport_aliases,
    )

    errors_by_line: dict[int, list[Finding]] = {}
    warnings_by_line: dict[int, list[Finding]] = {}
    for finding in summary.errors:
        errors_by_line.setdefault(finding.line_number, []).append(finding)
    for finding in summary.warnings:
        warnings_by_line.setdefault(finding.line_number, []).append(finding)

    outcomes: list[RouteOutcome] = []
    for row in rows:
        errors = errors_by_line.get(row.line_number, [])
        warnings = warnings_by_line.get(row.line_number, [])
        if errors:
            category = "lainoa_rebuild" if _is_lainoa(row.author) else "community_flag"
        else:
            category = "ok"
        outcomes.append(RouteOutcome(row=row, errors=errors, warnings=warnings, category=category))
    return outcomes


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
    navdata_path: Path,
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
        "generated_at_utc": datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "graph_db": str(graph_path),
        "navdata_db": str(navdata_path),
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
                        help="Path to navigraph_data.s3db — decides route acceptance")
    parser.add_argument("--airport-aliases", type=Path, help="Reviewed same-site aliases for the target AIRAC")
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
    # Hard guard: never modify routes for the bundled default AIRAC or older
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
    # Navdata is not optional here even though the flag is. Route acceptance is
    # decided against tbl_er_enroute_airways; without it the check falls back to
    # the compacted graph, which drops pass-through fixes, oceanic points and
    # cross-FIR airway halves — and this tool blanks what it rejects.
    if navdata_path is None or not navdata_path.exists():
        located = f": {navdata_path}" if navdata_path else ""
        print(
            f"ERROR: navdata is required to migrate routes{located}. Acceptance is decided "
            "against tbl_er_enroute_airways, not the compacted graph; running without it "
            "would blank correct routes.",
            file=sys.stderr,
        )
        return 1

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
    print(f"Validating {len(rows):,} routes against AIRAC {target_airac} navdata…")
    print(f"  Navdata: {navdata_path}", flush=True)
    print(f"  Graph:   {graph_path} (FRA DCT warnings only)", flush=True)
    try:
        outcomes = _validate_rows(
            routes_path, rows, graph_path, navdata_path, strict_dct=args.strict_dct,
            airport_aliases=load_airport_aliases(args.airport_aliases, target_airac),
        )
    except Exception as exc:
        print(f"ERROR validating routes: {exc}", file=sys.stderr)
        return 1

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
