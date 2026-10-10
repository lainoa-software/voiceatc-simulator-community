#!/usr/bin/env python3
"""Validate map_display.json files and generate the community manifest.

A map_display.json file curates an airport's radar map: the fixes, VORs and NDBs its
scope draws, and the MAPS layers that start on or off. The game (MapDisplaySync,
0.6.2 closed beta onward) shows only the listed points while the player keeps the FIX
row on CUR, and the player can switch to ALL or hide and show single points.

    {"airport": "LEBL", "schema": 1,
     "layers": {"VOR": true, "Low Airways": false},
     "fixes": ["SLL", {"ident": "RULOS", "lat": 41.2, "lon": 2.1}],
     "vors": ["BCN"], "ndbs": []}

A bare ident resolves in-game to the occurrence nearest the airport; an object with
lat/lon resolves to the occurrence nearest that position. An omitted list leaves that
point type uncurated; an empty list curates it to nothing.

Validation is structural (no navdata ships in this repo): JSON shape, airport==folder,
known layer names, ident format, coordinate ranges, no duplicates. The game skips an
ident it cannot resolve, so a typo hides one fix rather than breaking the airport.

Only builds with MapDisplaySync request `.voiceatc/map_display_manifest.json`, so it
needs no full-feed copy or channel gate. Its `schema_version` is the per-airport sync
engine's (1), the same value constraints and procedure options use.
"""
from __future__ import annotations

try:
    from .content_files import content_files
except ImportError:  # run as a script, or loaded by file path (tests)
    import sys
    from pathlib import Path

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from content_files import content_files

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".voiceatc" / "map_display_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
DISPLAY_FILENAME = "map_display.json"
# The game's per-airport sync engine accepts schema_version 1 only.
MANIFEST_SCHEMA_VERSION = 1
FILE_SCHEMA_VERSION = 1
LIST_KEYS = ("fixes", "vors", "ndbs")
TOP_LEVEL_KEYS = {"airport", "schema", "layers", "notes", *LIST_KEYS}
# The game's MAPS layer names (LAYERS in scripts/ui/pref_bar/map_layer_menu_button_base.gd).
LAYER_NAMES = (
    "VOR", "VOR Labels", "NDB", "NDB Labels", "FIX", "FIX Labels",
    "Low Airways", "High Airways", "GEO", "GEO Coastlines", "GEO Lakes", "GEO Rivers",
    "RWY", "RWY Labels", "MRVA", "MRVA Labels", "MISC", "MISC Labels", "ILS",
)
LAYERS_BY_UPPER = {name.upper(): name for name in LAYER_NAMES}
IDENT_RE = re.compile(r"^[A-Z0-9]{1,8}$")
VALIDATION_REPAIR_HINT = (
    "This manifest is CI-owned: format-all-json.yml refreshes it after every merge and "
    "daily-release.yml rebuilds it nightly, both with --write. A failure here means the "
    "writer and the checker disagree, which is a tooling bug rather than a contribution "
    "problem. Contributions are gated on --validate-sources, which ignores this manifest."
)


def display_files(root: Path = ROOT) -> list[Path]:
    return content_files(root, DISPLAY_FILENAME)


def ensure_text_field(value: object, label: str, path: Path) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: '{label}' must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{path}: '{label}' must not be empty")
    return text


def _number(value: object, label: str, low: float, high: float, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{path}: {label} must be a number between {low:g} and {high:g}")
    return float(value)


def _validate_layers(layers: object, path: Path) -> None:
    if not isinstance(layers, dict):
        raise ValueError(f"{path}: 'layers' must be a JSON object")
    seen: set[str] = set()
    for key, value in layers.items():
        name = LAYERS_BY_UPPER.get(str(key).strip().upper())
        if name is None:
            raise ValueError(
                f"{path}: layers.{key} is not a MAPS layer (one of: {', '.join(LAYER_NAMES)})"
            )
        if name in seen:
            raise ValueError(f"{path}: layers names '{name}' twice")
        seen.add(name)
        if not isinstance(value, bool):
            raise ValueError(f"{path}: layers.{key} must be true or false")


def _validate_list(entries: object, key: str, path: Path) -> None:
    if not isinstance(entries, list):
        raise ValueError(f"{path}: '{key}' must be an array")
    seen: set[tuple] = set()
    for index, entry in enumerate(entries):
        where = f"{key}[{index}]"
        if isinstance(entry, str):
            ident = entry.strip().upper()
            identity: tuple = (ident,)
        elif isinstance(entry, dict):
            unknown = set(entry) - {"ident", "lat", "lon"}
            if unknown:
                raise ValueError(f"{path}: {where} has unknown keys {sorted(unknown)}")
            ident = ensure_text_field(entry.get("ident"), f"{where}.ident", path).upper()
            if ("lat" in entry) != ("lon" in entry):
                raise ValueError(f"{path}: {where} needs both lat and lon, or neither")
            identity = (ident,)
            if "lat" in entry:
                lat = _number(entry["lat"], f"{where}.lat", -90, 90, path)
                lon = _number(entry["lon"], f"{where}.lon", -180, 180, path)
                identity = (ident, round(lat, 4), round(lon, 4))
        else:
            raise ValueError(f"{path}: {where} must be an ident string or an object")
        if not IDENT_RE.fullmatch(ident):
            raise ValueError(f"{path}: {where} ident '{ident}' must be 1-8 letters or digits")
        if identity in seen:
            raise ValueError(f"{path}: {where} repeats '{ident}'")
        seen.add(identity)


def validate_display_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: map display file must be a JSON object")
    unknown = set(payload) - TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(
            f"{path}: unknown keys {sorted(unknown)} (allowed: {', '.join(sorted(TOP_LEVEL_KEYS))})"
        )

    airport = ensure_text_field(payload.get("airport"), "airport", path).upper()
    parent_folder = path.parent.name.strip().upper()
    if airport != parent_folder:
        raise ValueError(f"{path}: airport '{airport}' must match parent folder '{parent_folder}'")
    if "schema" in payload and payload["schema"] != FILE_SCHEMA_VERSION:
        raise ValueError(f"{path}: 'schema' must be {FILE_SCHEMA_VERSION}")
    if "notes" in payload:
        ensure_text_field(payload["notes"], "notes", path)
    if "layers" in payload:
        _validate_layers(payload["layers"], path)
    for key in LIST_KEYS:
        if key in payload:
            _validate_list(payload[key], key, path)
    if "layers" not in payload and not any(key in payload for key in LIST_KEYS):
        raise ValueError(f"{path}: needs 'layers' or at least one of {', '.join(LIST_KEYS)}")

    canonical = raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return {
        "airport": airport,
        "repo_path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "size_bytes": len(canonical),
    }


def existing_published_at(path: Path = MANIFEST_PATH) -> str:
    """Read the stable publication time for byte-only maintenance rewrites."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid or missing manifest ({exc})") from exc
    value = str(payload.get("published_at", "")) if isinstance(payload, dict) else ""
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{path}: published_at must be an ISO-8601 UTC timestamp") from exc
    return value


def build_manifest(root: Path = ROOT, published_at: str | None = None) -> dict[str, object]:
    airports: dict[str, dict[str, object]] = {}
    for path in display_files(root):
        entry = validate_display_file(path, root)
        airport = str(entry["airport"])
        if airport in airports:
            raise ValueError(f"duplicate airport '{airport}' across map display files")
        airports[airport] = {
            "repo_path": entry["repo_path"],
            "sha256": entry["sha256"],
            "size_bytes": entry["size_bytes"],
        }
    if published_at is None:
        published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "airports": dict(sorted(airports.items())),
        "published_at": published_at,
    }


def _safe_relative_path(repo_path: str, root: Path) -> Path:
    candidate = (root / repo_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"manifest entry path escapes repository root: {repo_path}") from exc
    return candidate


def validate_existing_manifest_entries(
    root: Path = ROOT,
    manifest_path: Path = MANIFEST_PATH,
    expected_airports: set[str] | None = None,
) -> int:
    if not manifest_path.exists():
        raise ValueError(f"{manifest_path}: manifest is missing")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{manifest_path}: invalid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{manifest_path}: manifest must be a JSON object")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"{manifest_path}: schema_version must be {MANIFEST_SCHEMA_VERSION}")
    if str(payload.get("repo", "")).strip() != REPO_NAME:
        raise ValueError(f"{manifest_path}: repo must be '{REPO_NAME}'")
    airports = payload.get("airports", {})
    if not isinstance(airports, dict):
        raise ValueError(f"{manifest_path}: airports must be an object")

    if expected_airports is None:
        expected_airports = set(build_manifest(root, published_at="")["airports"])
    seen = {str(key).strip().upper() for key in airports}
    missing = sorted(expected_airports - seen)
    unexpected = sorted(seen - expected_airports)
    if missing or unexpected:
        differences = []
        if missing:
            differences.append(f"missing entries: {', '.join(missing)}")
        if unexpected:
            differences.append(f"unexpected entries: {', '.join(unexpected)}")
        raise ValueError(
            f"{manifest_path}: manifest airport set does not match source files ({'; '.join(differences)})"
        )

    for airport_key, entry in airports.items():
        airport = str(airport_key).strip().upper()
        if not isinstance(entry, dict):
            raise ValueError(f"{manifest_path}: entry for airport '{airport}' must be an object")
        repo_path = ensure_text_field(entry.get("repo_path"), "repo_path", manifest_path)
        candidate = _safe_relative_path(repo_path, root)
        if not candidate.is_file():
            raise ValueError(f"{manifest_path}: missing file for airport '{airport}' at '{repo_path}'")
        generated = validate_display_file(candidate, root)
        if generated["airport"] != airport:
            raise ValueError(
                f"{manifest_path}: airport key '{airport}' does not match file airport '{generated['airport']}'"
            )
        if str(entry.get("sha256", "")).strip().lower() != generated["sha256"]:
            raise ValueError(f"{manifest_path}: sha256 mismatch for airport '{airport}'")
        if int(entry.get("size_bytes", -1)) != generated["size_bytes"]:
            raise ValueError(f"{manifest_path}: size_bytes mismatch for airport '{airport}'")
    return len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate map_display.json files and generate the community map display manifest."
    )
    parser.add_argument("--write", action="store_true", help="Write .voiceatc/map_display_manifest.json")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Validate source files and the checked-in manifest (run this after --write)",
    )
    parser.add_argument(
        "--validate-sources", action="store_true",
        help="Validate source files only; the manifest is CI-owned",
    )
    parser.add_argument(
        "--preserve-published-at", action="store_true",
        help="Retain published_at while refreshing hashes after formatting",
    )
    args = parser.parse_args()
    if args.preserve_published_at and not args.write:
        parser.error("--preserve-published-at requires --write")

    try:
        published_at = None
        if args.preserve_published_at and MANIFEST_PATH.exists():
            published_at = existing_published_at()
        manifest = build_manifest(published_at=published_at)
        validated_entries = 0
        if args.validate_only:
            validated_entries = validate_existing_manifest_entries(
                expected_airports=set(manifest["airports"])
            )
    except Exception as exc:
        message = str(exc)
        if args.validate_only:
            message = f"{message}\n{VALIDATION_REPAIR_HINT}"
        print(message, file=sys.stderr)
        return 1

    if args.write:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"Wrote {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    elif args.validate_only:
        print(f"Validated {len(manifest['airports'])} map display files and {validated_entries} manifest entries.")
    elif args.validate_sources:
        print(f"Validated {len(manifest['airports'])} map display files.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
