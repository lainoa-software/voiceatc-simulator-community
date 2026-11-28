#!/usr/bin/env python3
"""Keep centre and tower seats from turning into approach seats.

A position's jobs are its ``roles``, or else follow from its unit's services. Two rules:

1. A position on an ``approach_radar`` unit that does only approach jobs works no sector
   reaching above FL300.
2. With ``--base <git ref>``, a position keeps every non-approach job it has on that ref,
   or it is removed together with the sectors it works there.

    python tools/seat_jobs_guard.py [--base origin/main]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from . import airac_overrides
except ImportError:  # run as a script, or loaded by file path (tests)
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import airac_overrides

ROOT = Path(__file__).resolve().parent.parent
APPROACH_JOBS = frozenset({"feeder", "final", "departure"})
SERVICE_JOBS = {
    "approach_radar": APPROACH_JOBS,
    "approach_conventional": APPROACH_JOBS,
    "tower": frozenset({"tower"}),
    "center": frozenset({"center"}),
}
CEILING_FEET = 30000
# Each definitions file and the layout beside it that gives its positions their sectors.
PAIRS = {"tma_definitions.json": "tma_layout.json", "acc_definitions.json": "acc_layout.json"}
ACC_FILE = "acc_definitions.json"
SECTOR_FILE = "sector_definitions.json"
FILE_NAMES = frozenset({*PAIRS, *PAIRS.values(), SECTOR_FILE})


@dataclass
class Seat:
    """One definition of a position."""

    file: str
    jobs: frozenset[str]
    services: frozenset[str]
    sectors: set[str] = field(default_factory=set)


@dataclass
class Tree:
    seats: dict[str, list[Seat]]
    ceilings: dict[str, float]  # every defined sector id, with the highest limit of its volumes


def _is_content(path: str) -> bool:
    """Content lives under the one-letter region folders."""
    parts = path.split("/")
    return len(parts) > 1 and len(parts[0]) == 1 and parts[-1] in FILE_NAMES


def read_directory(root: Path) -> dict[str, dict]:
    files = {}
    for path in sorted(root.glob("?/**/*.json")):
        name = path.relative_to(root).as_posix()
        if _is_content(name):
            files[name] = json.loads(path.read_text(encoding="utf-8-sig"))
    return files


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout.decode("utf-8-sig")


def read_ref(root: Path, ref: str) -> dict[str, dict]:
    names = _git(root, "ls-tree", "-r", "-z", "--name-only", ref).split("\0")
    return {name: json.loads(_git(root, "show", f"{ref}:{name}")) for name in names if _is_content(name)}


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0]


def _acc_folder(folder: str, files: dict[str, dict]) -> str:
    """The nearest folder above ``folder`` that holds acc_definitions.json, or ""."""
    while "/" in folder:
        folder = _parent(folder)
        if f"{folder}/{ACC_FILE}" in files:
            return folder
    return ""


def _sectors(files: dict[str, dict], folder: str) -> dict[str, dict]:
    """Sector id -> {"ceiling": feet, "made_of": [ids]} for one sector_definitions.json."""
    document = files.get(f"{folder}/{SECTOR_FILE}", {})
    result: dict[str, dict] = {}
    for sector_id, entry in document.get("sectors", {}).items():
        result[sector_id] = {"ceiling": 0.0, "made_of": entry.get("made_of", [])}
    for volume in document.get("volumes", []):
        for sector_id in volume.get("sector_ids", []):
            sector = result.setdefault(sector_id, {"ceiling": 0.0, "made_of": []})
            # A volume without a higher_limit has no ceiling.
            sector["ceiling"] = max(sector["ceiling"], volume.get("higher_limit", float("inf")))
    return result


def _expand(sector_id: str, catalog: dict[str, dict], seen: set[str]) -> None:
    if sector_id in seen:
        return
    seen.add(sector_id)
    for part in catalog.get(sector_id, {}).get("made_of", []):
        _expand(part, catalog, seen)


def _jobs(position: dict, services: frozenset[str]) -> frozenset[str]:
    if position.get("roles"):
        return frozenset(position["roles"])
    return frozenset().union(*(SERVICE_JOBS.get(name, frozenset()) for name in services))


def _services(unit: dict) -> frozenset[str]:
    if unit.get("services"):
        return frozenset(unit["services"])
    return frozenset({"center"}) if unit.get("part_of") else frozenset()


def load_tree(files: dict[str, dict]) -> Tree:
    tree = Tree({}, {})
    for path in files:
        if path.endswith(f"/{SECTOR_FILE}"):
            for sector_id, sector in _sectors(files, _parent(path)).items():
                tree.ceilings[sector_id] = max(tree.ceilings.get(sector_id, 0.0), sector["ceiling"])
    local: dict[tuple[str, str], Seat] = {}
    for path, document in files.items():
        folder, name = path.rsplit("/", 1)
        if name not in PAIRS:
            continue
        parent_acc = files.get(f"{_acc_folder(folder, files)}/{ACC_FILE}", {})
        units = {unit["id"]: unit for source in (parent_acc, document) for unit in source.get("units", [])}
        for position in document.get("positions", []):
            services = _services(units.get(position.get("unit"), {}))
            seat = Seat(path, _jobs(position, services), services)
            tree.seats.setdefault(position["call_sign"], []).append(seat)
            local[folder, position["call_sign"]] = seat
    for path, document in files.items():
        folder, name = path.rsplit("/", 1)
        if name not in PAIRS.values():
            continue
        acc = _acc_folder(folder, files)
        catalog = {**_sectors(files, acc), **_sectors(files, folder)}
        for configurations in document.get("configurations", {}).values():
            for configuration in configurations.values():
                for call_sign, sector_ids in configuration.get("positions", {}).items():
                    seat = local.get((folder, call_sign)) or local.get((acc, call_sign))
                    if seat is not None:
                        for sector_id in sector_ids:
                            _expand(sector_id, catalog, seat.sectors)
    return tree


def check_ceiling(head: Tree) -> list[str]:
    problems = []
    for call_sign, seats in sorted(head.seats.items()):
        for seat in seats:
            if not (seat.jobs and seat.jobs <= APPROACH_JOBS and "approach_radar" in seat.services):
                continue
            for sector_id in sorted(seat.sectors):
                ceiling = head.ceilings.get(sector_id, 0.0)
                if ceiling > CEILING_FEET:
                    top = "no upper limit" if ceiling == float("inf") else f"{ceiling:.0f} ft"
                    problems.append(
                        f"{seat.file}: {call_sign} is an approach seat but works sector {sector_id}, "
                        f"which reaches {top}. Approach seats stay at or below FL300 ({CEILING_FEET} ft)."
                    )
    return problems


def check_kept_jobs(base: Tree, head: Tree) -> list[str]:
    problems = []
    for call_sign, before in sorted(base.seats.items()):
        kept = set().union(*(seat.jobs for seat in before)) - APPROACH_JOBS
        if not kept:
            continue
        after = head.seats.get(call_sign)
        if after is None:
            left = sorted({s for seat in before for s in seat.sectors} & head.ceilings.keys())
            if left:
                problems.append(
                    f"{before[0].file}: {call_sign} was removed but its sectors are still defined "
                    f"({', '.join(left)}). A seat with a {', '.join(sorted(kept))} job can only be "
                    "removed together with its sectors."
                )
            continue
        for seat in after:
            lost = sorted(kept - seat.jobs)
            if lost:
                problems.append(
                    f"{seat.file}: {call_sign} lost the {', '.join(lost)} job. "
                    "Centre and tower jobs can't be removed from a seat."
                )
    return problems


def check(head_files: dict[str, dict], base_files: dict[str, dict] | None = None) -> list[str]:
    """Every problem in the default documents and in each AIRAC variant, once each."""
    problems: list[str] = []
    for tier in ("", *airac_overrides.TIERS):
        head = load_tree({path: airac_overrides.resolve(doc, tier) for path, doc in head_files.items()})
        problems += check_ceiling(head)
        if base_files is not None:
            base = load_tree({path: airac_overrides.resolve(doc, tier) for path, doc in base_files.items()})
            problems += check_kept_jobs(base, head)
    return list(dict.fromkeys(problems))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", help="git ref to compare seat jobs against")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    head_files = read_directory(args.root)
    base_files = read_ref(args.root, args.base) if args.base else None
    problems = check(head_files, base_files)
    for problem in problems:
        print(problem)
    if problems:
        print(f"Seat guard failed: {len(problems)} problem(s).")
        return 1
    seats = load_tree(head_files).seats
    compared = f", jobs compared with {args.base}" if args.base else ""
    print(f"Seat guard passed: {len(seats)} positions checked{compared}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
