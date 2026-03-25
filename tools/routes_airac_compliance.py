#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROUTES_PATH = ROOT / "ROUTES" / "routes.tsv"
AIRAC_REFERENCE_EFFECTIVE_DATE = date(2026, 1, 22)
AIRAC_STEP = timedelta(days=28)


@dataclass(frozen=True)
class AiracCycle:
    code: str
    effective_date: date
    next_effective_date: date


@dataclass(frozen=True)
class RoutesFileInfo:
    path: Path
    declared_airac: str
    route_count: int
    creation_airacs: tuple[str, ...]


@dataclass(frozen=True)
class ComplianceResult:
    routes: RoutesFileInfo
    active_cycle: AiracCycle
    older_creation_count: int
    newer_creation_airacs: tuple[str, ...]

    @property
    def is_compliant(self) -> bool:
        return self.routes.declared_airac == self.active_cycle.code and not self.newer_creation_airacs


def active_airac_cycle(target_date: date) -> AiracCycle:
    cycle_offset = (target_date - AIRAC_REFERENCE_EFFECTIVE_DATE).days // AIRAC_STEP.days
    effective_date = AIRAC_REFERENCE_EFFECTIVE_DATE + timedelta(days=cycle_offset * AIRAC_STEP.days)
    first_effective_date = effective_date
    while (first_effective_date - AIRAC_STEP).year == effective_date.year:
        first_effective_date -= AIRAC_STEP

    cycle_number = ((effective_date - first_effective_date).days // AIRAC_STEP.days) + 1
    code = f"{effective_date.year % 100:02d}{cycle_number:02d}"
    return AiracCycle(
        code=code,
        effective_date=effective_date,
        next_effective_date=effective_date + AIRAC_STEP,
    )


def parse_routes_file(routes_path: Path) -> RoutesFileInfo:
    raw_bytes = routes_path.read_bytes()
    text = raw_bytes.decode("utf-8-sig")
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"{routes_path}: file is empty")

    header = lines[0].strip()
    if not header.lower().startswith("airac "):
        raise ValueError(f"{routes_path}: first line must be 'airac <cycle>'")

    declared_airac = header[6:].strip()
    if not declared_airac.isdigit() or len(declared_airac) != 4:
        raise ValueError(f"{routes_path}: invalid AIRAC cycle '{declared_airac}'")

    route_count = 0
    creation_airacs: list[str] = []
    for line_number, raw_line in enumerate(lines[1:], start=2):
        line = raw_line.rstrip("\r\n")
        if not line.strip() or line.upper().startswith("ORIGIN"):
            continue

        parts = line.split("\t")
        if len(parts) < 3:
            raise ValueError(f"{routes_path}:{line_number}: expected at least 3 tab-separated columns")

        origin = parts[0].strip().upper()
        dest = parts[1].strip().upper()
        route = parts[2].strip().upper()
        creation_airac = parts[3].strip() if len(parts) >= 4 else ""

        if not origin or not dest:
            raise ValueError(f"{routes_path}:{line_number}: origin and dest must be non-empty")
        if not route:
            continue
        if creation_airac:
            if not creation_airac.isdigit() or len(creation_airac) != 4:
                raise ValueError(f"{routes_path}:{line_number}: invalid CREATION_AIRAC '{creation_airac}'")
            creation_airacs.append(creation_airac)
        route_count += 1

    if route_count <= 0:
        raise ValueError(f"{routes_path}: no route rows found")

    return RoutesFileInfo(
        path=routes_path,
        declared_airac=declared_airac,
        route_count=route_count,
        creation_airacs=tuple(creation_airacs),
    )


def validate_routes_file(routes_path: Path, target_date: date) -> ComplianceResult:
    routes = parse_routes_file(routes_path)
    active_cycle = active_airac_cycle(target_date)
    older_creation_count = sum(1 for value in routes.creation_airacs if value < routes.declared_airac)
    newer_creation_airacs = tuple(sorted({value for value in routes.creation_airacs if value > routes.declared_airac}))
    return ComplianceResult(
        routes=routes,
        active_cycle=active_cycle,
        older_creation_count=older_creation_count,
        newer_creation_airacs=newer_creation_airacs,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether ROUTES/routes.tsv declares the active AIRAC cycle.",
    )
    parser.add_argument(
        "--routes-path",
        default=str(DEFAULT_ROUTES_PATH),
        help="Path to the routes TSV file.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Date to evaluate in YYYY-MM-DD. Defaults to current UTC date.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    routes_path = Path(args.routes_path).resolve()
    if args.date.strip():
        try:
            target_date = date.fromisoformat(args.date.strip())
        except ValueError as exc:
            print(f"Invalid --date value '{args.date}': {exc}", file=sys.stderr)
            return 1
    else:
        target_date = datetime.now(timezone.utc).date()

    try:
        result = validate_routes_file(routes_path, target_date)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    status = "PASS" if result.is_compliant else "FAIL"
    print(f"{status} {routes_path}")
    print(f"Declared AIRAC: {result.routes.declared_airac}")
    print(
        "Active AIRAC: "
        f"{result.active_cycle.code} "
        f"(effective {result.active_cycle.effective_date.isoformat()}, "
        f"next {result.active_cycle.next_effective_date.isoformat()})"
    )
    print(f"Route rows: {result.routes.route_count}")
    if result.routes.creation_airacs:
        print(f"Older CREATION_AIRAC rows: {result.older_creation_count}")
    if result.newer_creation_airacs:
        print("Invalid newer CREATION_AIRAC values: " + ", ".join(result.newer_creation_airacs))

    return 0 if result.is_compliant else 1


if __name__ == "__main__":
    raise SystemExit(main())
