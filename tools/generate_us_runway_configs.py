#!/usr/bin/env python3
"""One-shot generator for FAA CY2024 top-50 US preferential runway configs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "documentation" / "content_hierarchy.json"

AIRPORT_CONFIGS: dict[str, list[dict[str, str]]] = {
    "KATL": [
        {"id": "WEST", "name": "WEST FLOW", "arr": "26R 27L", "dep": "26L 27R"},
        {"id": "EAST", "name": "EAST FLOW", "arr": "08L 09R", "dep": "08R 09L"},
    ],
    "KDFW": [
        {"id": "SOUTH_EAST", "name": "SOUTH FLOW EAST AIRFIELD", "arr": "17C 17L 17R", "dep": "17R 17C 17L"},
        {"id": "SOUTH_WEST", "name": "SOUTH FLOW WEST AIRFIELD", "arr": "18R 13R 18L", "dep": "18L 18R"},
        {"id": "NORTH_EAST", "name": "NORTH FLOW EAST AIRFIELD", "arr": "35C 35R 31R 35L", "dep": "35L 35C 35R"},
        {"id": "NORTH_WEST", "name": "NORTH FLOW WEST AIRFIELD", "arr": "36L 36R", "dep": "36R 36L"},
    ],
    "KDEN": [
        {"id": "NORTH_FLOW", "name": "NORTH FLOW", "arr": "34R 34L 35R 35L", "dep": "34L 34R 35L 35R"},
        {"id": "SOUTH_FLOW", "name": "SOUTH FLOW", "arr": "16L 16R 17L 17R", "dep": "08 17L 17R"},
        {"id": "NIGHT_NORTH", "name": "NIGHT NORTH FLOW", "arr": "26 34R 35L 35R 16L 16R", "dep": "08 35L 35R 34L 34R"},
    ],
    "KORD": [
        {"id": "FLYQUIET_14R", "name": "FLY QUIET ARR 14R", "arr": "14R", "dep": "28R 14R"},
        {"id": "FLYQUIET_27L", "name": "FLY QUIET ARR 27L", "arr": "27L", "dep": "28R 32L"},
        {"id": "FLYQUIET_22R", "name": "FLY QUIET ARR 22R", "arr": "22R", "dep": "28R 22R"},
        {"id": "FLYQUIET_10L", "name": "FLY QUIET ARR 10L", "arr": "10L", "dep": "09R 10L"},
    ],
    "KLAX": [
        {"id": "WEST", "name": "WEST TRAFFIC", "arr": "24R 25L", "dep": "24L 25R"},
        {"id": "EAST", "name": "EAST TRAFFIC", "arr": "06L 07R", "dep": "06R 07L"},
        {"id": "OVER_OCEAN", "name": "OVER-OCEAN OPS", "arr": "06R", "dep": "25R"},
        {"id": "NIGHT_INBOARD", "name": "NIGHT INBOARD PREF", "arr": "06R 24L 07L", "dep": "06R 24L 07L"},
    ],
    "KJFK": [
        {"id": "SOUTH_ARR", "name": "SOUTH FLOW ARR PRIORITY", "arr": "13L 22L", "dep": "13R"},
        {"id": "SOUTH_DEP", "name": "SOUTH FLOW DEP PRIORITY", "arr": "22L", "dep": "22R 31L"},
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "04R 04L", "dep": "04L 31L"},
        {"id": "NORTHWEST", "name": "NORTHWEST FLOW", "arr": "31R 31L", "dep": "31L"},
    ],
    "KCLT": [
        {"id": "SOUTH_3RWY", "name": "SOUTH OPS 3 RUNWAYS", "arr": "18R", "dep": "18C 18L"},
        {"id": "SOUTH_4RWY", "name": "SOUTH OPS 4 RUNWAYS", "arr": "18R 18C 18L 23", "dep": "18C 18L"},
        {"id": "NORTH_3RWY", "name": "NORTH OPS 3 RUNWAYS", "arr": "36L", "dep": "36C 36R"},
    ],
    "KLAS": [
        {"id": "WEST", "name": "WEST FLOW", "arr": "25L", "dep": "25R"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "19L 19R", "dep": "19L"},
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "01R 01L", "dep": "01R"},
        {"id": "EAST", "name": "EAST FLOW", "arr": "07L 07R", "dep": "07L"},
    ],
    "KMCO": [
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "17L 18R", "dep": "17R 18L"},
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "35R 36L", "dep": "35L 36R"},
    ],
    "KMIA": [
        {"id": "EAST", "name": "EAST FLOW DAY", "arr": "08L", "dep": "08R"},
        {"id": "WEST", "name": "WEST FLOW DAY", "arr": "26R", "dep": "26L"},
        {"id": "PARALLEL_09", "name": "PARALLEL 09/27", "arr": "09", "dep": "27"},
    ],
    "KPHX": [
        {"id": "EAST", "name": "EAST FLOW", "arr": "08 07R", "dep": "07L"},
        {"id": "WEST", "name": "WEST FLOW", "arr": "26 25L", "dep": "25R"},
    ],
    "KSEA": [
        {"id": "SOUTH_DAY", "name": "SOUTH FLOW DAY", "arr": "16R 16L 16C", "dep": "16L 16C"},
        {"id": "SOUTH_NIGHT", "name": "SOUTH FLOW NIGHT", "arr": "16L 16C", "dep": "16L 16C"},
        {"id": "NORTH_DAY", "name": "NORTH FLOW DAY", "arr": "34L 34R 34C", "dep": "34R 34C"},
        {"id": "NORTH_NIGHT", "name": "NORTH FLOW NIGHT", "arr": "34R 34C", "dep": "34R 34C"},
    ],
    "KSFO": [
        {"id": "WEST", "name": "WEST PLAN", "arr": "28L 28R", "dep": "01L 01R"},
        {"id": "SOUTHEAST", "name": "SOUTHEAST PLAN", "arr": "19L 19R 10L 10R", "dep": "19L 19R 10L 10R"},
        {"id": "NIGHT_10", "name": "NIGHT PREF RWY 10", "arr": "28L 28R", "dep": "10L 10R"},
    ],
    "KEWR": [
        {"id": "SOUTH", "name": "PARALLEL SOUTH FLOW", "arr": "04R 04L", "dep": "04L 04R"},
        {"id": "NORTH", "name": "PARALLEL NORTH FLOW", "arr": "22L 22R", "dep": "22L 22R"},
        {"id": "NIGHT", "name": "NIGHT PREF", "arr": "29", "dep": "04R 22L"},
        {"id": "HIGH_WIND_29", "name": "HIGH WIND ARR 29", "arr": "29", "dep": "22R"},
    ],
    "KIAH": [
        {"id": "WEST", "name": "WEST FLOW", "arr": "26R 26L 27", "dep": "15L 15R"},
        {"id": "EAST", "name": "EAST FLOW", "arr": "08L 08R", "dep": "15L 15R 09"},
        {"id": "WEST_NORTH", "name": "WEST NORTH FLOW", "arr": "26R 26L 27", "dep": "33L 33R"},
    ],
    "KBOS": [
        {"id": "NOISE_ABATE", "name": "NOISE ABATEMENT PREF", "arr": "33L", "dep": "15R"},
        {"id": "OVERNIGHT", "name": "OVERNIGHT HEAD-ON", "arr": "33L", "dep": "15R"},
    ],
    "KMSP": [
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "30L 30R 35", "dep": "30L 30R"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "12L 12R", "dep": "12L 12R 17"},
        {"id": "STRAIGHT_NORTH", "name": "STRAIGHT NORTH FLOW", "arr": "30L 30R", "dep": "30L 30R"},
    ],
    "KFLL": [
        {"id": "NORTH_PARALLEL", "name": "PREFERRED NORTH PARALLEL", "arr": "10L 28R", "dep": "10L 28R"},
        {"id": "EAST", "name": "EAST FLOW", "arr": "10L", "dep": "28R"},
        {"id": "WEST", "name": "WEST FLOW", "arr": "28R", "dep": "10L"},
    ],
    "KLGA": [
        {"id": "DAY", "name": "DAYTIME PREF", "arr": "22", "dep": "13"},
        {"id": "NIGHT", "name": "NIGHTTIME PREF", "arr": "22", "dep": "31"},
    ],
    "KDTW": [
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "21L 21R", "dep": "22L 22R"},
        {"id": "SOUTH_OIB", "name": "SOUTH OUTBOARD ARR", "arr": "22R 21L", "dep": "22L 21R"},
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "03R 03L", "dep": "04L 04R"},
        {"id": "NIGHT_CONTRA", "name": "NIGHT CONTRA-FLOW", "arr": "22L 22R", "dep": "22L 22R"},
    ],
    "KPHL": [
        {"id": "WEST", "name": "WEST PARALLEL FLOW", "arr": "27L 27R", "dep": "27L 27R"},
        {"id": "EAST", "name": "EAST PARALLEL FLOW", "arr": "09L 09R", "dep": "09L 09R"},
        {"id": "CROSSWIND", "name": "CROSSWIND 17/35", "arr": "35", "dep": "17"},
    ],
    "KSLC": [
        {"id": "ALTERNATING", "name": "ALTERNATING DAY FLOW", "arr": "34R 34L", "dep": "16R 16L"},
        {"id": "NORTH_PREF", "name": "NORTH FLOW PREFERRED", "arr": "34R 34L", "dep": "16R 16L 17"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "16R 16L 17", "dep": "34R 34L"},
    ],
    "KBWI": [
        {"id": "WEST", "name": "WEST OPS PREF", "arr": "10", "dep": "28"},
        {"id": "OVERNIGHT", "name": "OVERNIGHT 10/28 PREF", "arr": "10", "dep": "28"},
        {"id": "PARALLEL", "name": "PARALLEL 15/33", "arr": "33L", "dep": "15R"},
    ],
    "KIAD": [
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "01L 01C 01R", "dep": "01L 01C 01R"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "19L 19C 19R", "dep": "19L 19C 19R"},
        {"id": "CROSSWIND", "name": "CROSSWIND 12/30", "arr": "12", "dep": "30"},
    ],
    "KSAN": [
        {"id": "WEST", "name": "WEST TRAFFIC", "arr": "27", "dep": "27"},
        {"id": "EAST", "name": "EAST TRAFFIC", "arr": "09", "dep": "09"},
        {"id": "OPPOSITE", "name": "OPPOSITE DIRECTION", "arr": "09", "dep": "27"},
    ],
    "KDCA": [
        {"id": "NORTH", "name": "NORTH OPS", "arr": "01", "dep": "01"},
        {"id": "SOUTH", "name": "SOUTH OPS", "arr": "19", "dep": "19"},
        {"id": "NORTH_RW33", "name": "NORTH OPS RWY 33 ARR", "arr": "33", "dep": "01"},
    ],
    "KTPA": [
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "19L 19R", "dep": "19R 19L"},
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "01L 01R", "dep": "01L 01R"},
        {"id": "OVERNIGHT", "name": "OVERNIGHT PREF", "arr": "01L", "dep": "19R"},
        {"id": "EAST_WEST", "name": "EAST WEST FLOW", "arr": "10 28", "dep": "10 28"},
    ],
    "KBNA": [
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "02L 02C 02R", "dep": "02L 02C 02R"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "20L 20C 20R", "dep": "20L 20C 20R"},
        {"id": "MIL_TBJT", "name": "MIL TBJT NOISE", "arr": "13 31", "dep": "13 31"},
    ],
    "KAUS": [
        {"id": "OVERNIGHT", "name": "OVERNIGHT NOISE", "arr": "36L 36R", "dep": "18L 18R"},
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "18L 18R", "dep": "18L 18R"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "36L 36R", "dep": "36L 36R"},
    ],
    "PHNL": [
        {"id": "EAST", "name": "EAST OPS", "arr": "8L 8R 4R", "dep": "8L 8R 4R 4L"},
        {"id": "EAST_HEAVY", "name": "EAST OPS HEAVY DEP", "arr": "8L 8R 4R", "dep": "8R"},
        {"id": "WEST", "name": "WEST OPS", "arr": "26L 22L", "dep": "26R 22L"},
    ],
    "KMDW": [
        {"id": "NIGHT_DEP", "name": "NIGHT PREF DEP 22L", "arr": "04R 13L 31R", "dep": "22L"},
        {"id": "NIGHT_NOISE", "name": "NIGHT NOISE ABATEMENT", "arr": "04R 13L 31R", "dep": "04R 13L 22L 31R"},
    ],
    "KDAL": [
        {"id": "NIGHT_JET", "name": "NIGHT JET PREF", "arr": "13R 31L", "dep": "13R 31L"},
        {"id": "NIGHT_TRINITY", "name": "NIGHT TRINITY DEP", "arr": "13R 31L", "dep": "13R"},
    ],
    "KPDX": [
        {"id": "NIGHT_ARR", "name": "NIGHT PREF ARRIVALS", "arr": "10R 28R", "dep": "10R 10L 28R 28L"},
        {"id": "NIGHT_CONTRA", "name": "NIGHT CONTRA FLOW", "arr": "28L 28R", "dep": "10L 10R"},
        {"id": "WEST", "name": "WEST FLOW", "arr": "28L 28R", "dep": "28L 28R"},
    ],
    "KSTL": [
        {"id": "WEST", "name": "WEST CONFIG", "arr": "30L 30R", "dep": "30R 30L"},
        {"id": "EAST", "name": "EAST CONFIG", "arr": "12L 12R", "dep": "12L 12R"},
    ],
    "KRDU": [
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "23L 23R", "dep": "23L 23R"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "05L 05R", "dep": "05L 05R"},
    ],
    "KHOU": [
        {"id": "PARALLEL_13", "name": "PARALLEL 13/31", "arr": "13R 13L", "dep": "13R 31L"},
        {"id": "CROSSWIND", "name": "CROSSWIND 04/22", "arr": "04 22", "dep": "04 22"},
    ],
    "KSMF": [
        {"id": "NIGHT", "name": "NIGHT PREF 35", "arr": "35L 35R", "dep": "35L 35R"},
        {"id": "DAY", "name": "DAY FLOW 17", "arr": "17L 17R", "dep": "17L 17R"},
    ],
    "KMSY": [
        {"id": "PRIMARY", "name": "PRIMARY 11/29", "arr": "11 29", "dep": "11 29"},
        {"id": "CROSSWIND", "name": "CROSSWIND 02/20", "arr": "02 20", "dep": "02 20"},
    ],
    "TJSJ": [
        {"id": "EAST", "name": "EAST OPS", "arr": "10", "dep": "08"},
        {"id": "WEST", "name": "WEST OPS", "arr": "26", "dep": "28"},
    ],
    "KMCI": [
        {"id": "NIGHT", "name": "NIGHT NOISE ABATEMENT", "arr": "01L 19L", "dep": "01R 19R"},
        {"id": "NIGHT_NAM2", "name": "NIGHT NAM-2 PREF", "arr": "01L 19L", "dep": "01R 19R"},
        {"id": "NORTH_VOL", "name": "VOLUNTARY NORTH FLOW", "arr": "01L 01R 19L 19R", "dep": "01L 01R 19L 19R"},
    ],
    "KSJC": [
        {"id": "WEST", "name": "WEST JET NOISE", "arr": "30L", "dep": "30R"},
        {"id": "EAST", "name": "EAST JET NOISE", "arr": "12R", "dep": "12L"},
    ],
    "KSAT": [
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "13R", "dep": "13R"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "31L", "dep": "31L"},
        {"id": "CROSSWIND", "name": "CROSSWIND 04/22", "arr": "04", "dep": "22"},
    ],
    "KRSW": [
        {"id": "NIGHT", "name": "NIGHT PREF RWY 24", "arr": "24", "dep": "24"},
        {"id": "WEST", "name": "WEST FLOW", "arr": "24", "dep": "24"},
        {"id": "EAST", "name": "EAST FLOW", "arr": "06", "dep": "06"},
    ],
    "KSNA": [
        {"id": "PREF_DEP", "name": "PREFERRED DEPARTURES", "arr": "20L 20R", "dep": "20R 20L"},
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "20R", "dep": "20R"},
    ],
    "KOAK": [
        {"id": "JET_NOISE", "name": "JET NOISE 12/30", "arr": "30", "dep": "30"},
        {"id": "NORTH_FIELD", "name": "NORTH FIELD PARALLEL", "arr": "28R", "dep": "28L"},
        {"id": "SOUTH_FIELD", "name": "SOUTH FIELD 12", "arr": "12", "dep": "12"},
    ],
    "KIND": [
        {"id": "NE", "name": "NORTHEAST FLOW", "arr": "05L", "dep": "05R"},
        {"id": "SW", "name": "SOUTHWEST FLOW", "arr": "23R", "dep": "23L"},
        {"id": "CROSSWIND", "name": "CROSSWIND 14/32", "arr": "14", "dep": "32"},
    ],
    "KCLE": [
        {"id": "SOUTH", "name": "SOUTH WEST FLOW", "arr": "24L", "dep": "24R"},
        {"id": "NORTH", "name": "NORTH EAST FLOW", "arr": "06R", "dep": "06L"},
    ],
    "KPIT": [
        {"id": "WEST", "name": "WEST FLOW", "arr": "28L", "dep": "28R"},
        {"id": "EAST", "name": "EAST FLOW", "arr": "10R", "dep": "10L"},
        {"id": "CROSSWIND", "name": "CROSSWIND 32/14", "arr": "32", "dep": "14"},
    ],
    "KCVG": [
        {"id": "NIGHT", "name": "NIGHT NOISE", "arr": "09", "dep": "27"},
        {"id": "SOUTH", "name": "SOUTH FLOW", "arr": "18C", "dep": "18C"},
        {"id": "NORTH", "name": "NORTH FLOW", "arr": "36C", "dep": "36C"},
    ],
    "KCMH": [
        {"id": "NIGHT", "name": "NIGHT PREF SOUTH RWY", "arr": "10R", "dep": "28L"},
        {"id": "DAY", "name": "DAYTIME JET PREF", "arr": "28L", "dep": "10R"},
    ],
}


def airport_paths_from_registry() -> dict[str, str]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    terminal_scopes = registry.get("terminal_scopes", {})
    if not isinstance(terminal_scopes, dict):
        raise SystemExit(f"{REGISTRY_PATH}: terminal_scopes must be an object")
    registered_paths: dict[str, str] = {}
    for scope, airports in terminal_scopes.items():
        if not isinstance(scope, str) or not isinstance(airports, list):
            raise SystemExit(f"{REGISTRY_PATH}: invalid terminal scope entry")
        for icao in airports:
            if icao in registered_paths:
                raise SystemExit(f"{REGISTRY_PATH}: duplicate airport {icao}")
            registered_paths[str(icao)] = f"{scope}/{icao}"
    missing_paths = set(AIRPORT_CONFIGS) - set(registered_paths)
    if missing_paths:
        raise SystemExit(f"hierarchy registry is missing generator airports: {sorted(missing_paths)}")
    return {icao: registered_paths[icao] for icao in AIRPORT_CONFIGS}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify generated files without writing them")
    args = parser.parse_args()
    airport_paths = airport_paths_from_registry()
    mismatches: list[str] = []
    for icao, rel_path in sorted(airport_paths.items()):
        configs = AIRPORT_CONFIGS[icao]
        payload = {"airport": icao, "runway_configs": configs}
        out_dir = ROOT / rel_path
        out_file = out_dir / "runway_configs.json"
        expected = json.dumps(payload, indent=2) + "\n"
        if args.check:
            if not out_file.is_file() or out_file.read_text(encoding="utf-8") != expected:
                mismatches.append(out_file.relative_to(ROOT).as_posix())
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file.write_text(expected, encoding="utf-8")
        print(f"Wrote {out_file.relative_to(ROOT).as_posix()} ({len(configs)} configs)")

    if mismatches:
        raise SystemExit("Runway config generation check failed:\n- " + "\n- ".join(mismatches))
    action = "Checked" if args.check else "Total"
    print(f"{action} airports: {len(airport_paths)}")


if __name__ == "__main__":
    main()
