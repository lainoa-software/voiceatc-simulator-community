#!/usr/bin/env python3
"""Validate visual_sight_references.json sidecars and maintain their raw-file manifest."""
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
MANIFEST_PATH = ROOT / ".voiceatc" / "visual_sight_references_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
MAX_FILE_BYTES = 128 * 1024
MAX_VARIANTS = 64
MAX_REFERENCES = 8
MAX_ALIASES = 16
MAX_ROUTE_POINTS = 64
ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_]{0,79}$")
AIRPORT_RE = re.compile(r"^[A-Z]{4}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOP_KEYS = {"schema_version", "airport", "variants"}
VARIANT_KEYS = {"procedure_id", "variant_id", "default_reference_id", "references"}
REFERENCE_KEYS = {"id", "name", "aliases", "geometry", "source"}
SOURCE_KEYS = {"authority", "chart_title", "url", "effective_date", "airac", "checked_date"}
POINT_KEYS = {"kind", "leg_id", "latitude", "longitude"}
ROUTE_KEYS = {"kind", "leg_ids", "points"}
SIMPLE_GEOMETRY_KEYS = {"kind"}
POINT_VALUE_KEYS = {"latitude", "longitude"}
MANIFEST_KEYS = {"schema_version", "repo", "airports", "published_at"}
MANIFEST_ENTRY_KEYS = {"repo_path", "sha256", "size_bytes"}


def sight_reference_files(root: Path = ROOT) -> list[Path]:
    return content_files(root, "visual_sight_references.json")


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


def _text(value: object, where: str, path: Path, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{path}: {where} must be non-empty text up to {maximum} characters")
    return value.strip()


def _identifier(value: object, where: str, path: Path) -> str:
    result = _text(value, where, path, 80)
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


def _date(value: object, where: str, path: Path) -> str:
    result = _text(value, where, path, 10)
    if not DATE_RE.fullmatch(result):
        raise ValueError(f"{path}: {where} must be YYYY-MM-DD")
    try:
        datetime.strptime(result, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{path}: {where} must be a real calendar date") from exc
    return result


def _coordinate_pair(value: dict[str, Any], where: str, path: Path) -> None:
    _number(value.get("latitude"), f"{where}.latitude", path, -90, 90)
    _number(value.get("longitude"), f"{where}.longitude", path, -180, 180)


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
    if bool(effective) == bool(airac):
        raise ValueError(f"{path}: {where} needs exactly one effective_date or airac")
    if effective:
        _date(effective, f"{where}.effective_date", path)
    if airac and (len(airac) != 4 or not airac.isdigit()):
        raise ValueError(f"{path}: {where}.airac must be four digits")
    _date(source.get("checked_date"), f"{where}.checked_date", path)


def _validate_geometry(value: object, where: str, path: Path) -> None:
    geometry = _object(value, where, path)
    kind = str(geometry.get("kind", "")).strip().lower()
    if kind in {"airport", "runway"}:
        _strict_keys(geometry, SIMPLE_GEOMETRY_KEYS, where, path)
        return
    if kind == "point":
        _strict_keys(geometry, POINT_KEYS, where, path)
        has_leg = bool(str(geometry.get("leg_id", "")).strip())
        has_latitude = "latitude" in geometry
        has_longitude = "longitude" in geometry
        if has_leg == (has_latitude or has_longitude) or has_latitude != has_longitude:
            raise ValueError(
                f"{path}: {where} needs exactly one point representation: leg_id or coordinate pair"
            )
        if has_leg:
            _identifier(geometry.get("leg_id"), f"{where}.leg_id", path)
        else:
            _coordinate_pair(geometry, where, path)
        return
    if kind == "route":
        _strict_keys(geometry, ROUTE_KEYS, where, path)
        has_legs = "leg_ids" in geometry
        has_points = "points" in geometry
        if has_legs == has_points:
            raise ValueError(f"{path}: {where} needs exactly one leg_ids or points array")
        values = _array(geometry.get("leg_ids" if has_legs else "points"), where, path)
        if len(values) < 2 or len(values) > MAX_ROUTE_POINTS:
            raise ValueError(f"{path}: {where} must contain 2..{MAX_ROUTE_POINTS} entries")
        if has_legs:
            identifiers = [_identifier(item, f"{where}.leg_ids", path) for item in values]
            if len(set(identifiers)) != len(identifiers):
                raise ValueError(f"{path}: {where}.leg_ids must not contain duplicates")
        else:
            for index, item in enumerate(values):
                point_where = f"{where}.points[{index}]"
                point = _object(item, point_where, path)
                _strict_keys(point, POINT_VALUE_KEYS, point_where, path)
                _coordinate_pair(point, point_where, path)
        return
    raise ValueError(f"{path}: {where}.kind is unsupported")


def _phrase_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _visual_index(path: Path, tier: str = "") -> tuple[str, dict[tuple[str, str], list[str]]]:
    source_path = path.with_name("visual_procedures.json")
    if not source_path.is_file():
        raise ValueError(f"{path}: sibling visual_procedures.json is required")
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    visual = _object(airac_overrides.resolve(payload, tier), "visual procedures root", source_path)
    airport = str(visual.get("airport", "")).strip().upper()
    variants: dict[tuple[str, str], list[str]] = {}
    for procedure_value in visual.get("procedures", []):
        procedure = _object(procedure_value, "visual procedure", source_path)
        procedure_id = str(procedure.get("id", "")).strip().upper()
        for variant_value in procedure.get("variants", []):
            variant = _object(variant_value, "visual variant", source_path)
            key = (procedure_id, str(variant.get("id", "")).strip().upper())
            variants[key] = [
                str(_object(leg, "visual leg", source_path).get("id", "")).strip().upper()
                for leg in variant.get("legs", [])
            ]
    return airport, variants


def validate_sight_reference_schema(payload: dict[str, Any], path: Path, tier: str = "") -> None:
    _strict_keys(payload, TOP_KEYS, "root", path)
    if payload.get("schema_version") != LEGACY_VISUAL_SCHEMA_VERSION:
        raise ValueError(f"{path}: schema_version must be {LEGACY_VISUAL_SCHEMA_VERSION}")
    airport = _text(payload.get("airport"), "airport", path, 4).upper()
    if not AIRPORT_RE.fullmatch(airport):
        raise ValueError(f"{path}: airport must be a four-character ICAO")
    visual_airport, visual_variants = _visual_index(path, tier)
    if visual_airport != airport:
        raise ValueError(f"{path}: airport must match sibling visual_procedures.json")
    variants = _array(payload.get("variants"), "variants", path)
    if len(variants) > MAX_VARIANTS:
        raise ValueError(f"{path}: variants exceeds {MAX_VARIANTS} entries")
    seen_variants: set[tuple[str, str]] = set()
    for variant_index, value in enumerate(variants):
        where = f"variants[{variant_index}]"
        entry = _object(value, where, path)
        _strict_keys(entry, VARIANT_KEYS, where, path)
        key = (
            _identifier(entry.get("procedure_id"), f"{where}.procedure_id", path),
            _identifier(entry.get("variant_id"), f"{where}.variant_id", path),
        )
        if key in seen_variants:
            raise ValueError(f"{path}: duplicate sidecar variant {key[0]}/{key[1]}")
        seen_variants.add(key)
        if key not in visual_variants:
            raise ValueError(f"{path}: {where} must reference a matching visual procedure variant")
        references = _array(entry.get("references"), f"{where}.references", path)
        if not references or len(references) > MAX_REFERENCES:
            raise ValueError(f"{path}: {where}.references must contain 1..{MAX_REFERENCES} entries")
        seen_ids: set[str] = set()
        seen_phrases: set[str] = set()
        for reference_index, reference_value in enumerate(references):
            reference_where = f"{where}.references[{reference_index}]"
            reference = _object(reference_value, reference_where, path)
            _strict_keys(reference, REFERENCE_KEYS, reference_where, path)
            reference_id = _identifier(reference.get("id"), f"{reference_where}.id", path)
            if reference_id in seen_ids:
                raise ValueError(f"{path}: {reference_where}.id is duplicated")
            seen_ids.add(reference_id)
            phrases = [_text(reference.get("name"), f"{reference_where}.name", path, 120)]
            aliases = _array(reference.get("aliases"), f"{reference_where}.aliases", path)
            if len(aliases) > MAX_ALIASES:
                raise ValueError(f"{path}: {reference_where}.aliases exceeds {MAX_ALIASES}")
            phrases.extend(
                _text(alias, f"{reference_where}.aliases[{index}]", path, 120)
                for index, alias in enumerate(aliases)
            )
            for phrase in phrases:
                normalized = _phrase_key(phrase)
                if normalized in seen_phrases:
                    raise ValueError(f"{path}: {reference_where} duplicates a spoken name or alias")
                seen_phrases.add(normalized)
            geometry = _object(reference.get("geometry"), f"{reference_where}.geometry", path)
            _validate_geometry(geometry, f"{reference_where}.geometry", path)
            _validate_source(reference.get("source"), f"{reference_where}.source", path)
            leg_order = {leg_id: index for index, leg_id in enumerate(visual_variants[key])}
            if geometry.get("kind") == "point" and "leg_id" in geometry:
                leg_id = str(geometry["leg_id"]).upper()
                if leg_id not in leg_order:
                    raise ValueError(f"{path}: {reference_where} leg {leg_id} does not exist")
            if geometry.get("kind") == "route" and "leg_ids" in geometry:
                prior = -1
                for leg_id_value in geometry["leg_ids"]:
                    leg_id = str(leg_id_value).upper()
                    if leg_id not in leg_order:
                        raise ValueError(f"{path}: {reference_where} route leg {leg_id} does not exist")
                    current = leg_order[leg_id]
                    if current <= prior:
                        raise ValueError(f"{path}: {reference_where} route legs are not in source order")
                    prior = current
        default_id = _identifier(
            entry.get("default_reference_id"), f"{where}.default_reference_id", path
        )
        if default_id not in seen_ids:
            raise ValueError(f"{path}: {where}.default_reference_id does not name a reference")


def validate_sight_reference_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    if len(raw_bytes) > MAX_FILE_BYTES:
        raise ValueError(f"{path}: file exceeds {MAX_FILE_BYTES} bytes")
    payload = json.loads(raw_bytes.decode("utf-8"))
    airac_overrides.validate_references(payload, path)
    result = {}
    for tier in ("", "bundled", "latest"):
        document = airac_overrides.resolve(payload, tier)
        checked = _validate_sight_reference_document(document, path, root, raw_bytes, tier)
        if not tier:
            result = checked
    return result


def _validate_sight_reference_document(payload: dict, path: Path, root: Path, raw_bytes: bytes, tier: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: visual sight-reference file must be an object")
    validate_sight_reference_schema(payload, path, tier)
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
    for path in sight_reference_files(root):
        result = validate_sight_reference_file(path, root)
        airport = str(result["airport"])
        if airport in airports:
            raise ValueError(f"duplicate airport '{airport}' across visual sight-reference files")
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
    path = root / ".voiceatc" / "visual_sight_references_manifest.json"
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
        raise ValueError(
            f"{path}: manifest drift; run python tools/visual_sight_references_manifest.py --write"
        )
    for airport, value in airports.items():
        entry = _object(value, f"airports.{airport}", path)
        _strict_keys(entry, MANIFEST_ENTRY_KEYS, f"airports.{airport}", path)
        candidate = _safe_path(str(entry.get("repo_path", "")), root)
        if not candidate.is_file() or candidate.name != "visual_sight_references.json":
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
        MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"Wrote {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    elif args.validate_only:
        print(f"Validated {len(manifest['airports'])} visual sight-reference files and {count} manifest entries.")
    elif args.validate_sources:
        print(f"Validated {len(manifest['airports'])} visual sight-reference files.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
