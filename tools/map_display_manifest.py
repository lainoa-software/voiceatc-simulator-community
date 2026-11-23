#!/usr/bin/env python3
"""Validate map_display.json files and generate the community manifest.

A map_display.json file curates an airport's radar map: the fixes, VORs and NDBs its
scope draws, and the MAPS layers that start on or off. The game (MapDisplaySync,
0.6.2 closed beta onward) shows only the listed points while the player keeps the FIX
row on CUR, and the player can switch to ALL or hide and show single points.

    {"airport": "LEBL", "schema": 1,
     "layers": {"VOR": true, "Low Airways": false},
     "fixes": ["SLL", {"ident": "RULOS", "lat": 41.2, "lon": 2.1}],
     "vors": ["BCN"], "ndbs": [], "ils_length_nm": 25,
     "positions": {"LEBL_CORE_APP": {"layers": {"VOR": false}, "airspaces": ["CTR"],
                                     "fixes": ["VIBOK"]}}}

A bare ident resolves in-game to the occurrence nearest the airport; an object with
lat/lon resolves to the occurrence nearest that position. An omitted list leaves that
point type uncurated; an empty list curates it to nothing. A `positions` block, keyed by the
unit code New Session shows (LEBL_CORE_APP), applies only when the player works that
position: its layers over the airport's, its airspaces added to the opening AIRSPACES set,
and its fixes in place of the airport's.

Validation is structural (no navdata ships in this repo): JSON shape, airport==folder,
known layer names, ident format, coordinate ranges, no duplicates. The game skips an
ident it cannot resolve, so a typo hides one fix rather than breaking the airport.

Only builds with MapDisplaySync request `.voiceatc/map_display_manifest.json`, so it
needs no full-feed copy or channel gate. Its `schema_version` is the per-airport sync
engine's (1), the same value constraints and procedure options use.
"""
from __future__ import annotations

try:
    from . import airac_overrides, sector_legacy_projection
    from .content_files import content_files
except ImportError:  # run as a script, or loaded by file path (tests)
    import sys
    from pathlib import Path

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import airac_overrides
    import sector_legacy_projection
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
FILE_SCHEMA_VERSIONS = (1, 3)
LIST_KEYS = ("fixes", "vors", "ndbs")
ILS_LENGTH_KEY = "ils_length_nm"
# The game's ILS line length range (MIN/MAX_ILS_TICK_NM in scripts/world/levels/ils_spawner.gd).
ILS_LENGTH_RANGE = (1, 50)
SETTING_KEYS = ("layers", ILS_LENGTH_KEY, *LIST_KEYS)
POSITIONS_KEY = "positions"
POSITION_KEYS = {"layers", "airspaces", "fixes", "vors", "ndbs", ILS_LENGTH_KEY}
TOP_LEVEL_KEYS = {"airport", "schema", "notes", POSITIONS_KEY, *SETTING_KEYS}
# The game's MAPS layer names (LAYERS in scripts/ui/pref_bar/map_layer_menu_button_base.gd).
LAYER_NAMES = (
    "VOR", "VOR Labels", "NDB", "NDB Labels", "FIX", "FIX Labels",
    "Low Airways", "High Airways", "GEO", "GEO Coastlines", "GEO Lakes", "GEO Rivers",
    "RWY", "RWY Labels", "MRVA", "MRVA Labels", "MISC", "MISC Labels", "ILS",
)
LAYERS_BY_UPPER = {name.upper(): name for name in LAYER_NAMES}
IDENT_RE = re.compile(r"^[A-Z0-9]{1,8}$")
# A tma.json unit code: ICAO_part_TYPE or ICAO_TYPE (LEBL_CORE_APP, LEBL_TWR).
POSITION_CODE_RE = re.compile(r"^[A-Z0-9]+(_[A-Z0-9]+)+$")
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


def _validate_positions(positions: object, path: Path) -> None:
    if not isinstance(positions, dict) or not positions:
        raise ValueError(f"{path}: '{POSITIONS_KEY}' must be a JSON object of unit codes")
    for code, block in positions.items():
        where = f"{POSITIONS_KEY}.{code}"
        if not POSITION_CODE_RE.fullmatch(str(code)):
            raise ValueError(f"{path}: {where} must be a unit code such as LEBL_CORE_APP")
        if not isinstance(block, dict) or not block:
            raise ValueError(f"{path}: {where} must be an object with {', '.join(sorted(POSITION_KEYS))}")
        unknown = set(block) - POSITION_KEYS
        if unknown:
            raise ValueError(f"{path}: {where} has unknown keys {sorted(unknown)}")
        if "layers" in block:
            _validate_layers(block["layers"], path)
        if "airspaces" in block:
            names = block["airspaces"]
            if not isinstance(names, list):
                raise ValueError(f"{path}: {where}.airspaces must be an array")
            for index, name in enumerate(names):
                ensure_text_field(name, f"{where}.airspaces[{index}]", path)
            if len({str(name).strip().upper() for name in names}) != len(names):
                raise ValueError(f"{path}: {where}.airspaces repeats a name")
        if "fixes" in block:
            _validate_list(block["fixes"], f"{where}.fixes", path)
        for k in ("vors", "ndbs"):
            if k in block:
                _validate_list(block[k], f"{where}.{k}", path)
        if ILS_LENGTH_KEY in block:
            low, high = ILS_LENGTH_RANGE
            value = block[ILS_LENGTH_KEY]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{path}: '{where}.{ILS_LENGTH_KEY}' must be a whole number from {low} to {high}")


def _validate_display_document(payload: dict[str, object], path: Path) -> str:
    """Validate one resolved tier document against map display rules (schema 1 airport or schema 3 scope)."""
    unknown = set(payload) - TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(
            f"{path}: unknown keys {sorted(unknown)} (allowed: {', '.join(sorted(TOP_LEVEL_KEYS))})"
        )

    schema_val = payload.get("schema")
    if "schema" in payload:
        if isinstance(schema_val, bool) or schema_val not in FILE_SCHEMA_VERSIONS:
            raise ValueError(f"{path}: 'schema' must be 1 or 3")

    airport = ""
    if "airport" in payload:
        airport = ensure_text_field(payload.get("airport"), "airport", path).upper()
        parent_folder = path.parent.name.strip().upper()
        if airport != parent_folder:
            raise ValueError(f"{path}: airport '{airport}' must match parent folder '{parent_folder}'")
    elif schema_val != 3:
        ensure_text_field(payload.get("airport"), "airport", path)
    if "notes" in payload:
        ensure_text_field(payload["notes"], "notes", path)
    if "layers" in payload:
        _validate_layers(payload["layers"], path)
    if ILS_LENGTH_KEY in payload:
        low, high = ILS_LENGTH_RANGE
        value = payload[ILS_LENGTH_KEY]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{path}: '{ILS_LENGTH_KEY}' must be a whole number from {low} to {high}")
    for key in LIST_KEYS:
        if key in payload:
            _validate_list(payload[key], key, path)
    if POSITIONS_KEY in payload:
        _validate_positions(payload[POSITIONS_KEY], path)
    if not any(key in payload for key in (*SETTING_KEYS, POSITIONS_KEY)):
        raise ValueError(f"{path}: needs at least one of {', '.join((*SETTING_KEYS, POSITIONS_KEY))}")
    return airport


def _scope_airports(repo_path: str, root: Path) -> list[str]:
    files_index = sector_legacy_projection.load_frozen_files_index(root)
    matched: list[str] = []
    for legacy_rp, meta in sorted(files_index.items()):
        if meta.get("kind") == "map_display" and repo_path in (meta.get("sources") or {}):
            parts = legacy_rp.split("/")
            if len(parts) >= 2 and len(parts[-2]) == 4:
                matched.append(parts[-2].upper())
    if matched:
        return matched
    registry_path = root / "documentation" / "content_hierarchy.json"
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        scope = repo_path.rsplit("/", 1)[0]
        terminals = registry.get("terminal_scopes", {})
        if isinstance(terminals, dict):
            if scope in terminals and isinstance(terminals[scope], list) and terminals[scope]:
                return [str(a).strip().upper() for a in terminals[scope]]
            collected: list[str] = []
            for tscope, ap_list in terminals.items():
                if str(tscope).startswith(scope + "/") and isinstance(ap_list, list):
                    collected.extend(str(a).strip().upper() for a in ap_list)
            if collected:
                return sorted(set(collected))
    return []


def validate_display_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: map display file must be a JSON object")
    airport = ""
    has_variants = "airac_overrides" in payload
    for tier, document in airac_overrides.documents(payload):
        resolved_ap = _validate_display_document(document, path)
        if not tier:
            airport = resolved_ap

    repo_path = path.relative_to(root).as_posix()
    airports = [airport] if airport else _scope_airports(repo_path, root)
    canonical = raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return {
        "airport": airport,
        "airports": airports,
        "schema": payload.get("schema"),
        "has_variants": has_variants,
        "repo_path": repo_path,
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
        listed = entry.get("airports") or ([entry["airport"]] if entry.get("airport") else [])
        for airport in listed:  # type: ignore[union-attr]
            ap = str(airport)
            if ap in airports:
                raise ValueError(f"duplicate airport '{ap}' across map display files")
            airports[ap] = {
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
        if generated["airport"] and generated["airport"] != airport:
            raise ValueError(
                f"{manifest_path}: airport key '{airport}' does not match file airport '{generated['airport']}'"
            )
        if not generated["airport"] and airport not in (generated.get("airports") or []):
            raise ValueError(
                f"{manifest_path}: airport key '{airport}' is not in scope of '{repo_path}'"
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
        source_airports = {
            ap: str(entry["repo_path"])
            for ap, entry in manifest["airports"].items()  # type: ignore[union-attr]
        }
        files_index = sector_legacy_projection.load_frozen_files_index(ROOT)
        needs_full = False
        for rp in source_airports.values():
            doc = json.loads((ROOT / rp).read_text(encoding="utf-8"))
            if isinstance(doc, dict) and ("airac_overrides" in doc or doc.get("schema") == 3):
                needs_full = True
                break
        if needs_full:
            manifest = airac_overrides.publish_raw_manifest(
                ROOT, MANIFEST_PATH, manifest, requires=("community.airspace_files",)
            )
        for ap, entry in manifest["airports"].items():  # type: ignore[union-attr]
            orig_repo = source_airports[ap]
            raw_bytes = (ROOT / orig_repo).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            lookup_rp = orig_repo
            for frozen_rp, meta in files_index.items():
                if meta.get("kind") == "map_display" and orig_repo in (meta.get("sources") or {}):
                    if f"/{ap}/map_display.json" in frozen_rp or frozen_rp.startswith(f"{ap}/"):
                        lookup_rp = frozen_rp
                        break
            if lookup_rp == orig_repo and not orig_repo.endswith(f"/{ap}/map_display.json"):
                scope_dir = orig_repo.rsplit("/", 1)[0]
                lookup_rp = f"{scope_dir}/{ap}/map_display.json"
            leg_bytes = sector_legacy_projection.project_map_display_default_bytes(
                ROOT, lookup_rp, files_index=files_index
            )
            if leg_bytes != raw_bytes:
                dest_rel = f".voiceatc/defaults/{lookup_rp}"
                dest = ROOT / dest_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(leg_bytes)
                entry["repo_path"] = dest_rel
                entry["sha256"] = hashlib.sha256(leg_bytes).hexdigest()
                entry["size_bytes"] = len(leg_bytes)
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
