#!/usr/bin/env python3
"""Validate visual_go_arounds.json sidecars and maintain their raw-file manifest."""
from __future__ import annotations

try:
    from . import airac_overrides
    from .content_files import content_files
except ImportError:  # run as a script, or loaded by file path (tests)
    import sys
    from pathlib import Path

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import airac_overrides
    from content_files import content_files

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from legacy_contract import LEGACY_VISUAL_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".voiceatc" / "visual_go_arounds_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
MAX_FILE_BYTES = 128 * 1024
MAX_GO_AROUNDS = 64
MAX_LEGS = 32
ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_]{0,63}$")
AIRPORT_RE = re.compile(r"^[A-Z]{4}$")
RUNWAY_RE = re.compile(r"^(0[1-9]|[12][0-9]|3[0-6])[LRC]?$|^36[LRC]?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUPPORTED_TERMS = {
    "AF", "CA", "CD", "CF", "CI", "CR", "DF", "FA", "FC", "FD", "HF",
    "HM", "RF", "TF", "VA", "VD", "VI", "VM", "FM", "VR",
}
COORDINATE_TERMS = {"AF", "CF", "DF", "FA", "FC", "HF", "HM", "RF", "TF"}
COURSE_TERMS = {
    "AF", "CA", "CF", "CI", "CR", "FA", "FC", "HF", "HM", "RF", "VA",
    "VI", "VM", "FM", "VR",
}
TOP_KEYS = {"schema_version", "airport", "go_arounds"}
ENTRY_KEYS = {"procedure_id", "variant_id", "runway", "source", "terminal_policy", "legs"}
SOURCE_KEYS = {"authority", "chart_title", "url", "effective_date", "airac", "checked_date"}
LEG_KEYS = {
    "sequence", "ident", "path_term", "latitude", "longitude", "course",
    "turn_direction", "altitude1", "altitude2", "altitude_desc", "speed_limit",
    "distance", "description", "recommended_navaid", "recommended_navaid_latitude",
    "recommended_navaid_longitude", "theta", "rho", "arc_center_ident",
    "arc_center_latitude", "arc_center_longitude",
}
MANIFEST_KEYS = {"schema_version", "repo", "airports", "published_at"}
MANIFEST_ENTRY_KEYS = {"repo_path", "sha256", "size_bytes"}


def go_around_files(root: Path = ROOT) -> list[Path]:
    return content_files(root, "visual_go_arounds.json")


def _canonical_repo_bytes(raw_bytes: bytes) -> bytes:
    return re.sub(rb"\r+\n", b"\n", raw_bytes).replace(b"\r", b"\n")


def _object(value: object, where: str, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: {where} must be an object")
    return value


def _array(value: object, where: str, path: Path) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path}: {where} must be an array")
    return value


def _strict_keys(value: dict[str, Any], allowed: set[str], where: str, path: Path) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{path}: {where} has unknown keys: {', '.join(unknown)}")


def _text(value: object, where: str, path: Path, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{path}: {where} must be non-empty text up to {maximum} characters")
    return value.strip()


def _identifier(value: object, where: str, path: Path) -> str:
    result = _text(value, where, path, 64)
    if result != result.upper() or not ID_RE.fullmatch(result):
        raise ValueError(f"{path}: {where} must be a stable uppercase identifier")
    return result


def _number(value: object, where: str, path: Path, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: {where} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ValueError(f"{path}: {where} must be between {minimum:g} and {maximum:g}")
    return result


def _integer(value: object, where: str, path: Path, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}: {where} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{path}: {where} must be between {minimum} and {maximum}")
    return value


def _validate_coordinate_pair(
    value: dict[str, Any],
    latitude_key: str,
    longitude_key: str,
    where: str,
    path: Path,
    required_for: str = "",
) -> None:
    has_latitude = latitude_key in value
    has_longitude = longitude_key in value
    if has_latitude != has_longitude:
        raise ValueError(
            f"{path}: {where} must provide {latitude_key} and {longitude_key} together"
        )
    if required_for and not has_latitude:
        raise ValueError(f"{path}: {where} coordinates are required for {required_for}")
    if has_latitude:
        _number(value[latitude_key], f"{where}.{latitude_key}", path, -90, 90)
        _number(value[longitude_key], f"{where}.{longitude_key}", path, -180, 180)


def _date(value: object, where: str, path: Path) -> str:
    result = _text(value, where, path, 10)
    if not DATE_RE.fullmatch(result):
        raise ValueError(f"{path}: {where} must be YYYY-MM-DD")
    try:
        datetime.strptime(result, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{path}: {where} must be a real calendar date") from exc
    return result


def _validate_source(value: object, where: str, path: Path) -> None:
    source = _object(value, where, path)
    _strict_keys(source, SOURCE_KEYS, where, path)
    _text(source.get("authority"), f"{where}.authority", path, 80)
    _text(source.get("chart_title"), f"{where}.chart_title", path, 120)
    url = _text(source.get("url"), f"{where}.url", path, 500)
    if not url.startswith("https://") or " " in url:
        raise ValueError(f"{path}: {where}.url must be HTTPS")
    effective = str(source.get("effective_date", "")).strip()
    airac = str(source.get("airac", "")).strip()
    if not effective and not airac:
        raise ValueError(f"{path}: {where} needs effective_date or airac")
    if effective:
        _date(effective, f"{where}.effective_date", path)
    if airac and (len(airac) != 4 or not airac.isdigit()):
        raise ValueError(f"{path}: {where}.airac must be a four-digit cycle")
    _date(source.get("checked_date"), f"{where}.checked_date", path)


def _validate_leg(value: object, where: str, path: Path, prior_sequence: int) -> int:
    leg = _object(value, where, path)
    _strict_keys(leg, LEG_KEYS, where, path)
    sequence = _integer(leg.get("sequence"), f"{where}.sequence", path, 1, 1_000_000)
    if sequence <= prior_sequence:
        raise ValueError(f"{path}: {where}.sequence must increase in source order")
    _identifier(leg.get("ident"), f"{where}.ident", path)
    term = _text(leg.get("path_term"), f"{where}.path_term", path, 2).upper()
    if term not in SUPPORTED_TERMS:
        raise ValueError(f"{path}: {where}.path_term is unsupported")
    _validate_coordinate_pair(
        leg,
        "latitude",
        "longitude",
        where,
        path,
        term if term in COORDINATE_TERMS else "",
    )
    _validate_coordinate_pair(
        leg,
        "recommended_navaid_latitude",
        "recommended_navaid_longitude",
        where,
        path,
    )
    _validate_coordinate_pair(
        leg,
        "arc_center_latitude",
        "arc_center_longitude",
        where,
        path,
    )
    if term in COURSE_TERMS:
        _number(leg.get("course"), f"{where}.course", path, 0, 360)
    if "turn_direction" in leg and leg["turn_direction"] not in {"L", "R"}:
        raise ValueError(f"{path}: {where}.turn_direction must be L or R")
    altitude1 = _integer(leg.get("altitude1", 0), f"{where}.altitude1", path, 0, 100_000)
    altitude2 = _integer(leg.get("altitude2", 0), f"{where}.altitude2", path, 0, 100_000)
    descriptor = str(leg.get("altitude_desc", "")).upper()
    if descriptor not in {"", "+", "-", "@", "B"}:
        raise ValueError(f"{path}: {where}.altitude_desc is invalid")
    if descriptor == "B" and (altitude1 <= 0 or altitude2 <= altitude1):
        raise ValueError(f"{path}: {where} altitude window must be low-to-high")
    _integer(leg.get("speed_limit", 0), f"{where}.speed_limit", path, 0, 500)
    if "distance" in leg:
        _number(leg["distance"], f"{where}.distance", path, 0, 1000)
    return sequence


def _visual_keys(path: Path, tier: str = "") -> dict[tuple[str, str], str]:
    source = path.with_name("visual_procedures.json")
    if not source.is_file():
        raise ValueError(f"{path}: sibling visual_procedures.json is required")
    payload = airac_overrides.resolve(json.loads(source.read_text(encoding="utf-8")), tier)
    result: dict[tuple[str, str], str] = {}
    for procedure in payload.get("procedures", []):
        for variant in procedure.get("variants", []):
            result[(str(procedure.get("id")), str(variant.get("id")))] = str(variant.get("runway"))
    return result


def validate_go_around_schema(payload: dict[str, Any], path: Path, tier: str = "") -> None:
    _strict_keys(payload, TOP_KEYS, "root", path)
    if payload.get("schema_version") != LEGACY_VISUAL_SCHEMA_VERSION:
        raise ValueError(f"{path}: schema_version must be {LEGACY_VISUAL_SCHEMA_VERSION}")
    airport = _text(payload.get("airport"), "airport", path, 4).upper()
    if not AIRPORT_RE.fullmatch(airport):
        raise ValueError(f"{path}: airport must be a four-character ICAO")
    entries = _array(payload.get("go_arounds"), "go_arounds", path)
    if not entries or len(entries) > MAX_GO_AROUNDS:
        raise ValueError(f"{path}: go_arounds must contain 1..{MAX_GO_AROUNDS} entries")
    visual_keys = _visual_keys(path, tier)
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(entries):
        where = f"go_arounds[{index}]"
        entry = _object(value, where, path)
        _strict_keys(entry, ENTRY_KEYS, where, path)
        key = (
            _identifier(entry.get("procedure_id"), f"{where}.procedure_id", path),
            _identifier(entry.get("variant_id"), f"{where}.variant_id", path),
        )
        if key in seen:
            raise ValueError(f"{path}: duplicate go-around key {key[0]}/{key[1]}")
        seen.add(key)
        runway = _text(entry.get("runway"), f"{where}.runway", path, 3).upper()
        if not RUNWAY_RE.fullmatch(runway):
            raise ValueError(f"{path}: {where}.runway is invalid")
        if visual_keys.get(key) != runway:
            raise ValueError(f"{path}: {where} must reference a matching visual procedure variant")
        _validate_source(entry.get("source"), f"{where}.source", path)
        legs = _array(entry.get("legs"), f"{where}.legs", path)
        if not legs or len(legs) > MAX_LEGS:
            raise ValueError(f"{path}: {where}.legs must contain 1..{MAX_LEGS} legs")
        prior_sequence = 0
        for leg_index, leg in enumerate(legs):
            prior_sequence = _validate_leg(leg, f"{where}.legs[{leg_index}]", path, prior_sequence)
        terminal_term = str(legs[-1].get("path_term", "")).upper()
        expected_policy = (
            "HOLD_INDEFINITE" if terminal_term == "HM"
            else "HOLD_ONCE" if terminal_term == "HF"
            else "REQUEST_INSTRUCTIONS"
        )
        if entry.get("terminal_policy") != expected_policy:
            raise ValueError(f"{path}: {where}.terminal_policy does not match its final leg")


def validate_go_around_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    if len(raw_bytes) > MAX_FILE_BYTES:
        raise ValueError(f"{path}: file exceeds {MAX_FILE_BYTES} bytes")
    payload = json.loads(raw_bytes.decode("utf-8"))
    airac_overrides.validate_references(payload, path)
    result = {}
    for tier in ("", "bundled", "latest"):
        document = airac_overrides.resolve(payload, tier)
        checked = _validate_go_around_document(document, path, root, raw_bytes, tier)
        if not tier:
            result = checked
    return result


def _validate_go_around_document(payload: dict, path: Path, root: Path, raw_bytes: bytes, tier: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: visual go-arounds file must be an object")
    validate_go_around_schema(payload, path, tier)
    airport = str(payload["airport"]).upper()
    if airport != path.parent.name.upper():
        raise ValueError(f"{path}: airport must match its parent folder")
    canonical = _canonical_repo_bytes(raw_bytes)
    return {
        "airport": airport,
        "repo_path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "size_bytes": len(canonical),
    }


def build_manifest(root: Path = ROOT, published_at: str | None = None) -> dict[str, object]:
    airports: dict[str, dict[str, object]] = {}
    for path in go_around_files(root):
        result = validate_go_around_file(path, root)
        airport = str(result["airport"])
        if airport in airports:
            raise ValueError(f"duplicate airport '{airport}' across visual go-around files")
        airports[airport] = {
            "repo_path": result["repo_path"],
            "sha256": result["sha256"],
            "size_bytes": result["size_bytes"],
        }
    return {
        "schema_version": LEGACY_VISUAL_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "airports": dict(sorted(airports.items())),
        "published_at": published_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _safe_path(repo_path: str, root: Path) -> Path:
    posix = PurePosixPath(repo_path)
    if not repo_path or "\\" in repo_path or posix.is_absolute() or ".." in posix.parts:
        raise ValueError(f"manifest entry path is not canonical: {repo_path}")
    candidate = (root / repo_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"manifest entry path escapes repository root: {repo_path}") from exc
    return candidate


def validate_existing_manifest(root: Path = ROOT) -> int:
    path = root / ".voiceatc" / "visual_go_arounds_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: manifest must be an object")
    _strict_keys(payload, MANIFEST_KEYS, "manifest", path)
    if payload.get("schema_version") != LEGACY_VISUAL_SCHEMA_VERSION or payload.get("repo") != REPO_NAME:
        raise ValueError(f"{path}: invalid schema or repo")
    airports = _object(payload.get("airports"), "manifest.airports", path)
    published_at = str(payload.get("published_at", ""))
    _date(published_at[:10], "manifest.published_at", path)
    if airports != build_manifest(root, published_at)["airports"]:
        raise ValueError(f"{path}: manifest drift; run python tools/visual_go_arounds_manifest.py --write")
    for airport, value in airports.items():
        entry = _object(value, f"airports.{airport}", path)
        _strict_keys(entry, MANIFEST_ENTRY_KEYS, f"airports.{airport}", path)
        candidate = _safe_path(str(entry.get("repo_path", "")), root)
        if not candidate.is_file() or candidate.name != "visual_go_arounds.json":
            raise ValueError(f"{path}: unsafe or missing source path for '{airport}'")
    return len(airports)


def existing_published_at(path: Path = MANIFEST_PATH) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = str(payload.get("published_at", "")) if isinstance(payload, dict) else ""
    _date(value[:10], "manifest.published_at", path)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--validate-sources", action="store_true")
    parser.add_argument("--preserve-published-at", action="store_true")
    args = parser.parse_args()
    if args.preserve_published_at and not args.write:
        parser.error("--preserve-published-at requires --write")
    try:
        published_at = existing_published_at() if args.preserve_published_at else None
        manifest = build_manifest(published_at=published_at)
        count = validate_existing_manifest() if args.validate_only else 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.write:
        manifest = airac_overrides.publish_raw_manifest(ROOT, MANIFEST_PATH, manifest)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"Wrote {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    elif args.validate_only:
        print(f"Validated {len(manifest['airports'])} visual go-around files and {count} manifest entries.")
    elif args.validate_sources:
        print(f"Validated {len(manifest['airports'])} visual go-around files.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
