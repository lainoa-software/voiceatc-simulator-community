#!/usr/bin/env python3
"""Validate visual_procedures.json files and maintain their raw-file manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".voiceatc" / "visual_procedures_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
SCHEMA_VERSION = 1
MAX_FILE_BYTES = 256 * 1024
MAX_PROCEDURES = 64
MAX_LEGS = 128
MAX_ALIASES = 8
ADVISORY_DISTANCE_NM = 40.0
REJECT_DISTANCE_NM = 100.0
ARC_RADIUS_TOLERANCE_NM = 0.25
ARC_RADIUS_TOLERANCE_RATIO = 0.05
MAX_ARC_SWEEP_DEG = 300.0
EARTH_RADIUS_NM = 3440.065
ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_]{0,63}$")
AIRPORT_RE = re.compile(r"^[A-Z]{4}$")
RUNWAY_RE = re.compile(r"^(0[1-9]|[12][0-9]|3[0-6])[LRC]?$|^36[LRC]?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TOP_KEYS = {"schema_version", "airport", "procedures"}
PROCEDURE_KEYS = {
    "id", "name", "aliases", "classification", "policy_profile", "source",
    "availability", "variants",
}
SOURCE_KEYS = {"authority", "chart_title", "url", "effective_date", "airac", "checked_date"}
AVAILABILITY_KEYS = {"ceiling_ft", "visibility", "daylight_required", "tower_required", "notes"}
VISIBILITY_KEYS = {"value", "unit"}
VARIANT_KEYS = {
    "id", "runway", "clearance_name", "entry_point_id", "sight_reference_point_id",
    "join_policy", "sight_reference", "legs", "final",
}
SIGHT_REFERENCE_KEYS = {"name", "aliases", "scope"}
LEG_KEYS = {
    "id", "name", "path_term", "latitude", "longitude", "fly_over", "course_deg",
    "reference", "arc_center", "arc_radius_nm", "turn_direction", "altitude", "speed",
}
POINT_KEYS = {"latitude", "longitude"}
CONSTRAINT_KEYS = {"value_ft", "value2_ft", "value_kt", "status", "kind"}
FINAL_KEYS = {"course_deg", "glidepath_deg"}
MANIFEST_KEYS = {"schema_version", "repo", "airports", "published_at"}
MANIFEST_ENTRY_KEYS = {"repo_path", "sha256", "size_bytes"}
IGNORED_PARTS = {
    ".git",
    ".voiceatc",
    "node_modules",
    ".venv",
    "Backups",
    "Releases",
}


def visual_files(root: Path = ROOT) -> list[Path]:
    return sorted(
        path for path in root.rglob("visual_procedures.json")
        if not IGNORED_PARTS.intersection(path.parts)
    )


def _canonical_repo_bytes(raw_bytes: bytes) -> bytes:
    # A Windows checkout can hand a test fixture CRCRLF when a CRLF buffer is
    # passed through text-mode newline conversion twice. Treat one or more CRs
    # before LF as the same logical line ending, then normalise bare CR too.
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


def _text(value: object, where: str, path: Path, *, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {where} must be non-empty text")
    clean = value.strip()
    if len(clean) > maximum:
        raise ValueError(f"{path}: {where} exceeds {maximum} characters")
    return clean


def _identifier(value: object, where: str, path: Path) -> str:
    clean = _text(value, where, path, maximum=64)
    if clean != clean.upper() or not ID_RE.fullmatch(clean):
        raise ValueError(f"{path}: {where} must be a stable uppercase identifier")
    return clean


def _number(value: object, where: str, path: Path, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: {where} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ValueError(f"{path}: {where} must be between {minimum:g} and {maximum:g}")
    return result


def _coordinate(value: dict[str, Any], where: str, path: Path) -> tuple[float, float]:
    latitude = _number(value.get("latitude"), f"{where}.latitude", path, -90.0, 90.0)
    longitude = _number(value.get("longitude"), f"{where}.longitude", path, -180.0, 180.0)
    return latitude, longitude


def _date(value: object, where: str, path: Path) -> str:
    text = _text(value, where, path, maximum=10)
    if not DATE_RE.fullmatch(text):
        raise ValueError(f"{path}: {where} must be YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{path}: {where} must be a real calendar date") from exc
    return text


def _distance_nm(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_NM * 2 * math.atan2(math.sqrt(hav), math.sqrt(max(0.0, 1.0 - hav)))


def _bearing_deg(origin: tuple[float, float], target: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, target)
    delta_lon = lon2 - lon1
    y = math.sin(delta_lon) * math.cos(lat2)
    x = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    )
    return math.degrees(math.atan2(y, x)) % 360.0


def _arc_sweep_deg(
    center: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    turn_direction: str,
) -> float:
    start_bearing = _bearing_deg(center, start)
    end_bearing = _bearing_deg(center, end)
    if turn_direction == "R":
        return (end_bearing - start_bearing) % 360.0
    return (start_bearing - end_bearing) % 360.0


def _validate_constraint(value: object, value_key: str, where: str, path: Path) -> None:
    if value is None:
        return
    constraint = _object(value, where, path)
    _strict_keys(constraint, CONSTRAINT_KEYS, where, path)
    first_value = _number(
        constraint.get(value_key), f"{where}.{value_key}", path, 0.0, 100000.0
    )
    if constraint.get("status") not in {"required", "recommended"}:
        raise ValueError(f"{path}: {where}.status must be required or recommended")
    kind = constraint.get("kind")
    allowed_kinds = {"at", "at_or_above", "at_or_below"}
    if value_key == "value_ft":
        allowed_kinds.add("between")
    if kind not in allowed_kinds:
        raise ValueError(f"{path}: {where}.kind is invalid")
    if kind == "between":
        second_value = _number(
            constraint.get("value2_ft"), f"{where}.value2_ft", path, 0.0, 100000.0
        )
        if second_value <= first_value:
            raise ValueError(f"{path}: {where}.value2_ft must exceed value_ft")
    elif "value2_ft" in constraint:
        raise ValueError(f"{path}: {where}.value2_ft is only valid for an altitude window")
    if value_key == "value_kt" and "value_ft" in constraint:
        raise ValueError(f"{path}: {where}.value_ft is invalid for a speed constraint")
    if value_key == "value_ft" and "value_kt" in constraint:
        raise ValueError(f"{path}: {where}.value_kt is invalid for an altitude constraint")


def _validate_source(value: object, where: str, path: Path) -> None:
    source = _object(value, where, path)
    _strict_keys(source, SOURCE_KEYS, where, path)
    _text(source.get("authority"), f"{where}.authority", path, maximum=80)
    _text(source.get("chart_title"), f"{where}.chart_title", path, maximum=120)
    url = _text(source.get("url"), f"{where}.url", path, maximum=500)
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


def _validate_availability(value: object, where: str, path: Path) -> None:
    if value is None:
        return
    availability = _object(value, where, path)
    _strict_keys(availability, AVAILABILITY_KEYS, where, path)
    if "ceiling_ft" in availability:
        _number(availability["ceiling_ft"], f"{where}.ceiling_ft", path, 0.0, 60000.0)
    if "visibility" in availability:
        visibility = _object(availability["visibility"], f"{where}.visibility", path)
        _strict_keys(visibility, VISIBILITY_KEYS, f"{where}.visibility", path)
        _number(visibility.get("value"), f"{where}.visibility.value", path, 0.001, 1000.0)
        if visibility.get("unit") not in {"SM", "KM", "M"}:
            raise ValueError(f"{path}: {where}.visibility.unit must be SM, KM, or M")
    for key in ("daylight_required", "tower_required"):
        if key in availability and not isinstance(availability[key], bool):
            raise ValueError(f"{path}: {where}.{key} must be boolean")
    if "notes" in availability:
        _text(availability["notes"], f"{where}.notes", path)


def _validate_leg(value: object, where: str, path: Path) -> tuple[str, tuple[float, float]]:
    leg = _object(value, where, path)
    _strict_keys(leg, LEG_KEYS, where, path)
    leg_id = _identifier(leg.get("id"), f"{where}.id", path)
    _text(leg.get("name"), f"{where}.name", path, maximum=80)
    path_term = str(leg.get("path_term", "")).upper()
    if path_term not in {"TF", "CF", "RF", "AF"}:
        raise ValueError(f"{path}: {where}.path_term must be TF, CF, RF, or AF")
    position = _coordinate(leg, where, path)
    if not isinstance(leg.get("fly_over"), bool):
        raise ValueError(f"{path}: {where}.fly_over must be boolean")
    if path_term == "CF":
        _number(leg.get("course_deg"), f"{where}.course_deg", path, 0.0, 360.0)
        if "reference" in leg and not isinstance(leg["reference"], str):
            raise ValueError(f"{path}: {where}.reference must be text")
    elif any(key in leg for key in ("course_deg", "reference")):
        raise ValueError(f"{path}: {where} course/reference fields are only valid for CF legs")
    if path_term in {"RF", "AF"}:
        center = _object(leg.get("arc_center"), f"{where}.arc_center", path)
        _strict_keys(center, POINT_KEYS, f"{where}.arc_center", path)
        _coordinate(center, f"{where}.arc_center", path)
        _number(leg.get("arc_radius_nm"), f"{where}.arc_radius_nm", path, 0.01, REJECT_DISTANCE_NM)
        if leg.get("turn_direction") not in {"L", "R"}:
            raise ValueError(f"{path}: {where}.turn_direction must be L or R")
    elif any(key in leg for key in ("arc_center", "arc_radius_nm", "turn_direction")):
        raise ValueError(f"{path}: {where} arc fields are only valid for RF or AF legs")
    _validate_constraint(leg.get("altitude"), "value_ft", f"{where}.altitude", path)
    _validate_constraint(leg.get("speed"), "value_kt", f"{where}.speed", path)
    return leg_id, position


def _validate_variant(value: object, where: str, path: Path, advisories: list[str]) -> str:
    variant = _object(value, where, path)
    _strict_keys(variant, VARIANT_KEYS, where, path)
    variant_id = _identifier(variant.get("id"), f"{where}.id", path)
    runway = _text(variant.get("runway"), f"{where}.runway", path, maximum=3).upper()
    if not RUNWAY_RE.fullmatch(runway):
        raise ValueError(f"{path}: {where}.runway is invalid")
    _text(variant.get("clearance_name"), f"{where}.clearance_name", path, maximum=80)
    join_policy = variant.get("join_policy", "entry_required")
    if join_policy not in {"entry_required", "forward_route"}:
        raise ValueError(
            f"{path}: {where}.join_policy must be entry_required or forward_route"
        )
    if "sight_reference" in variant:
        sight_reference = _object(
            variant["sight_reference"], f"{where}.sight_reference", path
        )
        _strict_keys(
            sight_reference,
            SIGHT_REFERENCE_KEYS,
            f"{where}.sight_reference",
            path,
        )
        _text(
            sight_reference.get("name"),
            f"{where}.sight_reference.name",
            path,
            maximum=80,
        )
        aliases = _array(
            sight_reference.get("aliases"),
            f"{where}.sight_reference.aliases",
            path,
        )
        if len(aliases) > MAX_ALIASES:
            raise ValueError(
                f"{path}: {where}.sight_reference.aliases exceeds {MAX_ALIASES}"
            )
        normalized_aliases: set[str] = set()
        for index, alias in enumerate(aliases):
            spoken = _text(
                alias,
                f"{where}.sight_reference.aliases[{index}]",
                path,
                maximum=64,
            ).upper()
            if spoken in normalized_aliases:
                raise ValueError(f"{path}: duplicate sight-reference alias '{spoken}'")
            normalized_aliases.add(spoken)
        if sight_reference.get("scope") not in {"point", "route"}:
            raise ValueError(
                f"{path}: {where}.sight_reference.scope must be point or route"
            )
    legs = _array(variant.get("legs"), f"{where}.legs", path)
    if not legs or len(legs) > MAX_LEGS:
        raise ValueError(f"{path}: {where}.legs must contain 1..{MAX_LEGS} legs")
    leg_ids: list[str] = []
    positions: list[tuple[float, float]] = []
    for index, leg in enumerate(legs):
        leg_id, position = _validate_leg(leg, f"{where}.legs[{index}]", path)
        if leg_id in leg_ids:
            raise ValueError(f"{path}: duplicate leg id '{leg_id}'")
        leg_ids.append(leg_id)
        positions.append(position)
    entry_id = _identifier(variant.get("entry_point_id"), f"{where}.entry_point_id", path)
    sight_id = _identifier(variant.get("sight_reference_point_id"), f"{where}.sight_reference_point_id", path)
    if entry_id != leg_ids[0]:
        raise ValueError(f"{path}: {where}.entry_point_id must reference the first leg")
    if sight_id not in leg_ids:
        raise ValueError(f"{path}: {where}.sight_reference_point_id must reference one leg")
    for index, position in enumerate(positions[1:], start=1):
        distance = _distance_nm(positions[0], position)
        if distance > REJECT_DISTANCE_NM:
            raise ValueError(f"{path}: {where}.legs[{index}] is over 100 NM from the entry")
        if distance > ADVISORY_DISTANCE_NM:
            advisories.append(f"{path}: {where}.legs[{index}] is over 40 NM from the entry")
    for left_index, left in enumerate(positions):
        for right_index in range(left_index + 1, len(positions)):
            distance = _distance_nm(left, positions[right_index])
            if distance > REJECT_DISTANCE_NM:
                raise ValueError(
                    f"{path}: {where}.legs[{right_index}] is over 100 NM from leg {left_index}"
                )
            if distance > ADVISORY_DISTANCE_NM:
                advisories.append(
                    f"{path}: {where}.legs[{right_index}] is over 40 NM from leg {left_index}"
                )
    for index, leg_value in enumerate(legs):
        leg = _object(leg_value, f"{where}.legs[{index}]", path)
        if leg.get("path_term") not in {"RF", "AF"}:
            continue
        if index == 0:
            raise ValueError(f"{path}: {where}.legs[0] cannot start with an arc")
        center_value = _object(leg["arc_center"], f"{where}.legs[{index}].arc_center", path)
        center = _coordinate(center_value, f"{where}.legs[{index}].arc_center", path)
        radius = float(leg["arc_radius_nm"])
        tolerance = max(ARC_RADIUS_TOLERANCE_NM, radius * ARC_RADIUS_TOLERANCE_RATIO)
        for endpoint_name, endpoint in (
            ("start", positions[index - 1]),
            ("end", positions[index]),
        ):
            endpoint_radius = _distance_nm(center, endpoint)
            if abs(endpoint_radius - radius) > tolerance:
                raise ValueError(
                    f"{path}: {where}.legs[{index}] arc {endpoint_name} is "
                    f"{endpoint_radius:.2f} NM from its center; expected {radius:.2f} NM"
                )
        sweep = _arc_sweep_deg(
            center,
            positions[index - 1],
            positions[index],
            str(leg["turn_direction"]),
        )
        if sweep > MAX_ARC_SWEEP_DEG:
            raise ValueError(
                f"{path}: {where}.legs[{index}] arc sweep is {sweep:.1f} degrees; "
                f"maximum is {MAX_ARC_SWEEP_DEG:.0f} degrees"
            )
    if "final" in variant:
        final = _object(variant["final"], f"{where}.final", path)
        _strict_keys(final, FINAL_KEYS, f"{where}.final", path)
        if "course_deg" in final:
            _number(final["course_deg"], f"{where}.final.course_deg", path, 0.0, 360.0)
        if "glidepath_deg" in final:
            _number(final["glidepath_deg"], f"{where}.final.glidepath_deg", path, 0.1, 10.0)
    return variant_id


def validate_visual_schema(payload: dict[str, Any], path: Path) -> list[str]:
    _strict_keys(payload, TOP_KEYS, "root", path)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path}: schema_version must be {SCHEMA_VERSION}")
    airport = _text(payload.get("airport"), "airport", path, maximum=4).upper()
    if not AIRPORT_RE.fullmatch(airport):
        raise ValueError(f"{path}: airport must be a four-character ICAO")
    procedures = _array(payload.get("procedures"), "procedures", path)
    if not procedures:
        raise ValueError(f"{path}: procedures must not be empty")
    if len(procedures) > MAX_PROCEDURES:
        raise ValueError(f"{path}: procedures exceeds {MAX_PROCEDURES}")
    procedure_ids: set[str] = set()
    spoken_tokens: set[str] = set()
    advisories: list[str] = []
    for proc_index, value in enumerate(procedures):
        where = f"procedures[{proc_index}]"
        procedure = _object(value, where, path)
        _strict_keys(procedure, PROCEDURE_KEYS, where, path)
        procedure_id = _identifier(procedure.get("id"), f"{where}.id", path)
        if procedure_id in procedure_ids:
            raise ValueError(f"{path}: duplicate procedure id '{procedure_id}'")
        procedure_ids.add(procedure_id)
        name = _text(procedure.get("name"), f"{where}.name", path, maximum=120)
        aliases = _array(procedure.get("aliases"), f"{where}.aliases", path)
        if len(aliases) > MAX_ALIASES:
            raise ValueError(f"{path}: {where}.aliases exceeds {MAX_ALIASES}")
        for token in [name, *aliases]:
            spoken = _text(token, f"{where}.aliases", path, maximum=64).upper()
            if spoken in spoken_tokens:
                raise ValueError(f"{path}: duplicate spoken alias '{spoken}'")
            spoken_tokens.add(spoken)
        if procedure.get("classification") != "charted_ifr_visual":
            raise ValueError(f"{path}: {where}.classification must be charted_ifr_visual")
        if procedure.get("policy_profile") not in {"FAA", "ICAO"}:
            raise ValueError(f"{path}: {where}.policy_profile must be FAA or ICAO")
        _validate_source(procedure.get("source"), f"{where}.source", path)
        _validate_availability(procedure.get("availability"), f"{where}.availability", path)
        variants = _array(procedure.get("variants"), f"{where}.variants", path)
        if not variants:
            raise ValueError(f"{path}: {where}.variants must not be empty")
        variant_ids: set[str] = set()
        for variant_index, variant in enumerate(variants):
            variant_id = _validate_variant(variant, f"{where}.variants[{variant_index}]", path, advisories)
            if variant_id in variant_ids:
                raise ValueError(f"{path}: duplicate variant id '{variant_id}'")
            variant_ids.add(variant_id)
    return advisories


def validate_visual_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    if len(raw_bytes) > MAX_FILE_BYTES:
        raise ValueError(f"{path}: file exceeds {MAX_FILE_BYTES} bytes")
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: visual procedures file must be an object")
    advisories = validate_visual_schema(payload, path)
    airport = str(payload["airport"]).upper()
    if airport != path.parent.name.upper():
        raise ValueError(f"{path}: airport '{airport}' must match parent folder '{path.parent.name}'")
    canonical = _canonical_repo_bytes(raw_bytes)
    return {
        "airport": airport,
        "repo_path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "size_bytes": len(canonical),
        "advisories": advisories,
    }


def build_manifest(root: Path = ROOT, published_at: str | None = None) -> dict[str, object]:
    airports: dict[str, dict[str, object]] = {}
    for path in visual_files(root):
        result = validate_visual_file(path, root)
        airport = str(result["airport"])
        if airport in airports:
            raise ValueError(f"duplicate airport '{airport}' across visual procedure files")
        airports[airport] = {
            "repo_path": result["repo_path"],
            "sha256": result["sha256"],
            "size_bytes": result["size_bytes"],
        }
    if published_at is None:
        published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": SCHEMA_VERSION,
        "repo": REPO_NAME,
        "airports": dict(sorted(airports.items())),
        "published_at": published_at,
    }


def _safe_path(repo_path: str, root: Path) -> Path:
    if not repo_path or "\\" in repo_path or re.match(r"^[A-Za-z]:", repo_path):
        raise ValueError(f"manifest entry path is not canonical: {repo_path}")
    posix_path = PurePosixPath(repo_path)
    if posix_path.is_absolute() or any(part in {"", "."} for part in posix_path.parts):
        raise ValueError(f"manifest entry path is not canonical: {repo_path}")
    candidate = (root / repo_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"manifest entry path escapes repository root: {repo_path}") from exc
    if ".." in posix_path.parts:
        raise ValueError(f"manifest entry path is not canonical: {repo_path}")
    return candidate


def validate_existing_manifest(root: Path = ROOT, manifest_path: Path | None = None) -> int:
    target = manifest_path or (root / ".voiceatc" / "visual_procedures_manifest.json")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{target}: invalid or missing manifest ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{target}: manifest must be an object")
    _strict_keys(payload, MANIFEST_KEYS, "manifest", target)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{target}: schema_version must be {SCHEMA_VERSION}")
    if payload.get("repo") != REPO_NAME or not isinstance(payload.get("airports"), dict):
        raise ValueError(f"{target}: invalid repo or airports mapping")
    _date(str(payload.get("published_at", ""))[:10], "manifest.published_at", target)
    generated = build_manifest(root, published_at=str(payload.get("published_at", "")))
    if payload.get("airports") != generated.get("airports"):
        raise ValueError(f"{target}: manifest drift; run python tools/visual_procedures_manifest.py --write")
    for airport, entry in payload["airports"].items():
        if not AIRPORT_RE.fullmatch(str(airport)):
            raise ValueError(f"{target}: airport key '{airport}' must be a four-character ICAO")
        if not isinstance(entry, dict):
            raise ValueError(f"{target}: entry for '{airport}' must be an object")
        _strict_keys(entry, MANIFEST_ENTRY_KEYS, f"airports.{airport}", target)
        repo_path = _text(entry.get("repo_path"), f"airports.{airport}.repo_path", target, maximum=500)
        candidate = _safe_path(repo_path, root)
        if not candidate.is_file() or candidate.name != "visual_procedures.json":
            raise ValueError(f"{target}: unsafe or missing source path for '{airport}'")
        generated_entry = validate_visual_file(candidate, root)
        if generated_entry["airport"] != airport:
            raise ValueError(f"{target}: airport key '{airport}' does not match source file")
        if entry.get("sha256") != generated_entry["sha256"]:
            raise ValueError(f"{target}: sha256 mismatch for airport '{airport}'")
        if entry.get("size_bytes") != generated_entry["size_bytes"]:
            raise ValueError(f"{target}: size_bytes mismatch for airport '{airport}'")
    return len(payload["airports"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        manifest = build_manifest()
        count = validate_existing_manifest() if args.validate_only else 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.write:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Wrote {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    elif args.validate_only:
        print(f"Validated {len(manifest['airports'])} visual procedure files and {count} manifest entries.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
