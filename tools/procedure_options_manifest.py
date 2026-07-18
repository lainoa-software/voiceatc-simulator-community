#!/usr/bin/env python3
"""Validate procedure_options.json files and generate the community manifest.

A procedure_options.json file carries per-procedure attributes for an airport,
keyed by procedure ident inside `stars` / `sids` / `iaps` buckets. The attribute
consumed by the simulator are `spawn_enabled` (whether auto-traffic may be
assigned the procedure) and `init_climb` (the initial cleared altitude in feet
for a generated departure). The per-procedure object remains open for future
attributes without changing this tool or the file's distribution.

An optional top-level `runways` object lets a curator override the per-procedure
flag for a specific landing/departure direction: each key is a bare runway token
(e.g. "25") whose `stars`/`sids`/`iaps` sub-objects use the same per-procedure
shape. The simulator resolves per-runway override → global per-procedure value →
the matching default → the built-in fallback.

Validation here is structural only (the same scope as constraints_manifest.py):
JSON shape, airport==folder, bucket/entry types, boolean flags. Procedure idents
are NOT cross-checked against navdata (none ships in this repo); a mistyped ident
is a harmless no-op in-game (it simply matches nothing and stays enabled).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".voiceatc" / "procedure_options_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
SCHEMA_VERSION = 1
OPTIONS_FILENAME = "procedure_options.json"
BUCKETS = ("stars", "sids", "iaps")
CLIMB_RULE_KINDS = ("route_contains", "aircraft_type", "utc_window", "fallback")
CLIMB_PATH_TERMS = ("IF", "TF", "DF", "CF", "CA", "VA", "VM", "FM")
RUNWAY_TOKEN_RE = re.compile(r"^[0-9]{1,2}[LRCB]?$")
NAVAID_IDENT_RE = re.compile(r"^[A-Z0-9]{2,8}$")
IGNORED_PARTS = {
    ".git",
    ".voiceatc",
    "node_modules",
    ".venv",
    "Backups",
    "Releases",
    ".codex",
    "logs",
}


def options_files(root: Path = ROOT) -> list[Path]:
    return sorted(
        path
        for path in root.rglob(OPTIONS_FILENAME)
        if not any(part in IGNORED_PARTS for part in path.parts)
    )


def ensure_text_field(value: object, label: str, path: Path) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: '{label}' must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{path}: '{label}' must not be empty")
    return text


def _canonical_repo_bytes(raw_bytes: bytes) -> bytes:
    """Match the LF bytes stored and served by Git, regardless of checkout EOL."""
    return raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _positive_number(value: object, where: str, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{path}: {where} must be a positive number")
    return float(value)


def _heading(value: object, where: str, path: Path) -> float:
    heading = _positive_number(value, where, path)
    if heading > 360:
        raise ValueError(f"{path}: {where} must be between 1 and 360 degrees")
    return heading


def _navaid_ident(value: object, where: str, path: Path) -> str:
    ident = ensure_text_field(value, where, path).upper()
    if not NAVAID_IDENT_RE.fullmatch(ident):
        raise ValueError(f"{path}: {where} must be a 2-8 character navaid ident")
    return ident


def _validate_crossing_candidate(candidate: object, where: str, path: Path) -> None:
    if not isinstance(candidate, dict):
        raise ValueError(f"{path}: {where} must be a JSON object")
    kind = ensure_text_field(candidate.get("kind"), f"{where}.kind", path).lower()
    if kind not in ("dme", "radial"):
        raise ValueError(f"{path}: {where}.kind must be 'dme' or 'radial'")
    _navaid_ident(candidate.get("navaid"), f"{where}.navaid", path)
    if kind == "dme":
        _positive_number(candidate.get("distance_nm"), f"{where}.distance_nm", path)
    else:
        _heading(candidate.get("radial"), f"{where}.radial", path)


def _validate_containment(assertions: object, where: str, path: Path) -> None:
    if not isinstance(assertions, list) or not assertions:
        raise ValueError(f"{path}: {where} must be a non-empty array")
    for index, assertion in enumerate(assertions):
        item_where = f"{where}[{index}]"
        if not isinstance(assertion, dict):
            raise ValueError(f"{path}: {item_where} must be a JSON object")
        kind = ensure_text_field(assertion.get("kind"), f"{item_where}.kind", path).lower()
        if kind not in ("east_of_radial", "max_dme"):
            raise ValueError(f"{path}: {item_where}.kind is unsupported")
        _navaid_ident(assertion.get("navaid"), f"{item_where}.navaid", path)
        if kind == "east_of_radial":
            _heading(assertion.get("radial"), f"{item_where}.radial", path)
        else:
            _positive_number(assertion.get("distance_nm"), f"{item_where}.distance_nm", path)


def _validate_climb_leg(leg: object, where: str, path: Path) -> None:
    if not isinstance(leg, dict):
        raise ValueError(f"{path}: {where} must be a JSON object")
    path_term = ensure_text_field(leg.get("path_term"), f"{where}.path_term", path).upper()
    if path_term not in CLIMB_PATH_TERMS:
        raise ValueError(f"{path}: {where}.path_term '{path_term}' is unsupported")
    if "ident" in leg:
        ensure_text_field(leg["ident"], f"{where}.ident", path)
    if "course" in leg:
        _heading(leg["course"], f"{where}.course", path)
    if path_term in ("CA", "VA", "VM", "FM", "CF") and "course" not in leg:
        raise ValueError(f"{path}: {where}.course is required for {path_term}")
    if "turn_direction" in leg:
        turn = ensure_text_field(leg["turn_direction"], f"{where}.turn_direction", path).upper()
        if turn not in ("L", "R"):
            raise ValueError(f"{path}: {where}.turn_direction must be 'L' or 'R'")
    for key in ("altitude1", "altitude2", "speed_limit", "distance_nm"):
        if key in leg:
            _positive_number(leg[key], f"{where}.{key}", path)
    if "altitude_description" in leg:
        desc = ensure_text_field(leg["altitude_description"], f"{where}.altitude_description", path).upper()
        if desc not in ("+", "-", "@", "B"):
            raise ValueError(f"{path}: {where}.altitude_description is unsupported")
    if "recommended_navaid" in leg:
        _navaid_ident(leg["recommended_navaid"], f"{where}.recommended_navaid", path)
    if "endpoint" in leg:
        endpoint = leg["endpoint"]
        if not isinstance(endpoint, dict):
            raise ValueError(f"{path}: {where}.endpoint must be a JSON object")
        if str(endpoint.get("kind", "")).lower() != "radial_dme":
            raise ValueError(f"{path}: {where}.endpoint.kind must be 'radial_dme'")
        _navaid_ident(endpoint.get("navaid"), f"{where}.endpoint.navaid", path)
        _heading(endpoint.get("radial"), f"{where}.endpoint.radial", path)
        _positive_number(endpoint.get("distance_nm"), f"{where}.endpoint.distance_nm", path)
    if "crossing" in leg:
        crossing = leg["crossing"]
        if not isinstance(crossing, dict):
            raise ValueError(f"{path}: {where}.crossing must be a JSON object")
        ensure_text_field(crossing.get("id"), f"{where}.crossing.id", path)
        first_of = crossing.get("first_of")
        if not isinstance(first_of, list) or len(first_of) < 2:
            raise ValueError(f"{path}: {where}.crossing.first_of must contain at least two alternatives")
        for index, candidate in enumerate(first_of):
            _validate_crossing_candidate(candidate, f"{where}.crossing.first_of[{index}]", path)
        for key in ("altitude1", "altitude2"):
            if key in crossing:
                _positive_number(crossing[key], f"{where}.crossing.{key}", path)
    if "containment" in leg:
        _validate_containment(leg["containment"], f"{where}.containment", path)


def _validate_auto_rule(rule: object, where: str, path: Path) -> str:
    if not isinstance(rule, dict):
        raise ValueError(f"{path}: {where} must be a JSON object")
    kind = ensure_text_field(rule.get("kind"), f"{where}.kind", path).lower()
    if kind not in CLIMB_RULE_KINDS:
        raise ValueError(f"{path}: {where}.kind '{kind}' is unsupported")
    if kind in ("route_contains", "aircraft_type"):
        values = rule.get("values")
        if not isinstance(values, list) or not values:
            raise ValueError(f"{path}: {where}.values must be a non-empty array")
        for index, value in enumerate(values):
            ensure_text_field(value, f"{where}.values[{index}]", path)
    elif kind == "utc_window":
        start = rule.get("start_minute")
        end = rule.get("end_minute")
        if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start < 1440:
            raise ValueError(f"{path}: {where}.start_minute must be an integer from 0 to 1439")
        if isinstance(end, bool) or not isinstance(end, int) or not 0 <= end <= 1440:
            raise ValueError(f"{path}: {where}.end_minute must be an integer from 0 to 1440")
        if start == end:
            raise ValueError(f"{path}: {where} UTC window must not be empty")
    return kind


def _validate_climb_variants(container: object, where: str, path: Path) -> None:
    if not isinstance(container, list) or not container:
        raise ValueError(f"{path}: {where} must be a non-empty array")
    seen_ids: set[str] = set()
    fallback_indices: list[int] = []
    for index, variant in enumerate(container):
        variant_where = f"{where}[{index}]"
        if not isinstance(variant, dict):
            raise ValueError(f"{path}: {variant_where} must be a JSON object")
        variant_id = ensure_text_field(variant.get("id"), f"{variant_where}.id", path).upper()
        if variant_id in seen_ids:
            raise ValueError(f"{path}: duplicate climb variant id '{variant_id}'")
        seen_ids.add(variant_id)
        ensure_text_field(variant.get("display_name"), f"{variant_where}.display_name", path)
        runways = variant.get("runways")
        if not isinstance(runways, list) or not runways:
            raise ValueError(f"{path}: {variant_where}.runways must be a non-empty array")
        for runway_index, runway in enumerate(runways):
            token = ensure_text_field(runway, f"{variant_where}.runways[{runway_index}]", path).upper()
            if not RUNWAY_TOKEN_RE.fullmatch(token):
                raise ValueError(f"{path}: {variant_where}.runways[{runway_index}] is invalid")
        kind = _validate_auto_rule(variant.get("auto_rule"), f"{variant_where}.auto_rule", path)
        if kind == "fallback":
            fallback_indices.append(index)
        legs = variant.get("legs")
        if not isinstance(legs, list) or not legs:
            raise ValueError(f"{path}: {variant_where}.legs must be a non-empty array")
        for leg_index, leg in enumerate(legs):
            _validate_climb_leg(leg, f"{variant_where}.legs[{leg_index}]", path)
    if fallback_indices != [len(container) - 1]:
        raise ValueError(f"{path}: {where} must contain exactly one final fallback rule")


def _validate_option_entry(
    container: object,
    where: str,
    path: Path,
    allow_climb_variants: bool = False,
) -> None:
    if not isinstance(container, dict):
        raise ValueError(f"{path}: {where} must be a JSON object")
    if "spawn_enabled" in container and not isinstance(container["spawn_enabled"], bool):
        raise ValueError(f"{path}: {where}.spawn_enabled must be true or false")
    if "init_climb" in container:
        init_climb = container["init_climb"]
        if isinstance(init_climb, bool) or not isinstance(init_climb, int) or init_climb <= 0:
            raise ValueError(f"{path}: {where}.init_climb must be a positive integer feet value")
    if "climb_variants" in container:
        if not allow_climb_variants:
            raise ValueError(f"{path}: {where}.climb_variants is only supported on SID entries")
        _validate_climb_variants(container["climb_variants"], f"{where}.climb_variants", path)


def _validate_transitions(container: object, where: str, path: Path) -> None:
    """Validate a `transitions` block: an optional blanket `spawn_enabled` bool
    (forbids/allows every approach feeder at once) plus optional per-feeder
    `{spawn_enabled: bool}` objects keyed by transition ident."""
    if not isinstance(container, dict):
        raise ValueError(f"{path}: '{where}' must be a JSON object")
    for key, value in container.items():
        if key == "spawn_enabled":
            if not isinstance(value, bool):
                raise ValueError(f"{path}: {where}.spawn_enabled must be true or false")
            continue
        _validate_option_entry(value, f"{where}.{key}", path)


def _validate_buckets(payload: dict[str, object], prefix: str, path: Path) -> None:
    for bucket in BUCKETS:
        if bucket not in payload:
            continue
        bucket_payload = payload[bucket]
        if not isinstance(bucket_payload, dict):
            raise ValueError(f"{path}: '{prefix}{bucket}' must be a JSON object")
        for proc_ident, entry in bucket_payload.items():
            _validate_option_entry(
                entry,
                f"{prefix}{bucket}.{proc_ident}",
                path,
                allow_climb_variants=bucket == "sids",
            )


def _validate_direction_overrides(
    payload: dict[str, object],
    key: str,
    path: Path,
) -> None:
    if key not in payload:
        return
    overrides = payload[key]
    if not isinstance(overrides, dict):
        raise ValueError(f"{path}: '{key}' must be a JSON object")
    for override_key, override_payload in overrides.items():
        if not isinstance(override_key, str) or not override_key.strip():
            raise ValueError(f"{path}: {key} key must be a non-empty string")
        if not isinstance(override_payload, dict):
            raise ValueError(f"{path}: '{key}.{override_key}' must be a JSON object")
        _validate_buckets(override_payload, f"{key}.{override_key}.", path)
        if "transitions" in override_payload:
            _validate_transitions(
                override_payload["transitions"],
                f"{key}.{override_key}.transitions",
                path,
            )


def validate_options_schema(payload: dict[str, object], path: Path) -> None:
    if "defaults" in payload:
        _validate_option_entry(payload["defaults"], "defaults", path)
    for key in ("schema_version", "airac_min"):
        if key in payload and not isinstance(payload[key], int):
            raise ValueError(f"{path}: '{key}' must be an integer")
    _validate_buckets(payload, "", path)
    if "transitions" in payload:
        _validate_transitions(payload["transitions"], "transitions", path)
    _validate_direction_overrides(payload, "runways", path)
    _validate_direction_overrides(payload, "configs", path)


def validate_options_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    canonical_bytes = _canonical_repo_bytes(raw_bytes)
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{path}: procedure options file must be a JSON object")

    airport = ensure_text_field(payload.get("airport"), "airport", path).upper()
    parent_folder = path.parent.name.strip().upper()
    if airport != parent_folder:
        raise ValueError(f"{path}: airport '{airport}' must match parent folder '{parent_folder}'")

    validate_options_schema(payload, path)

    repo_path = path.relative_to(root).as_posix()
    return {
        "airport": airport,
        "repo_path": repo_path,
        "sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "size_bytes": len(canonical_bytes),
    }


def build_manifest(
    root: Path = ROOT,
    published_at: str | None = None,
) -> dict[str, object]:
    airports: dict[str, dict[str, object]] = {}
    for path in options_files(root):
        entry = validate_options_file(path, root)
        airport = str(entry["airport"])
        if airport in airports:
            raise ValueError(f"duplicate airport '{airport}' across procedure options files")
        airports[airport] = {
            "repo_path": entry["repo_path"],
            "sha256": entry["sha256"],
            "size_bytes": entry["size_bytes"],
        }

    if published_at is None:
        published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "schema_version": SCHEMA_VERSION,
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


def validate_existing_manifest_entries(root: Path = ROOT, manifest_path: Path = MANIFEST_PATH) -> int:
    if not manifest_path.exists():
        return 0

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{manifest_path}: invalid JSON ({exc})") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{manifest_path}: manifest must be a JSON object")

    if int(payload.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError(f"{manifest_path}: schema_version must be {SCHEMA_VERSION}")

    repo = str(payload.get("repo", "")).strip()
    if repo != REPO_NAME:
        raise ValueError(f"{manifest_path}: repo must be '{REPO_NAME}'")

    airports = payload.get("airports", {})
    if not isinstance(airports, dict):
        raise ValueError(f"{manifest_path}: airports must be an object")

    seen_airports: set[str] = set()
    for airport_key, entry in airports.items():
        airport = str(airport_key).strip().upper()
        if not airport:
            raise ValueError(f"{manifest_path}: airport key must not be empty")
        if airport in seen_airports:
            raise ValueError(f"{manifest_path}: duplicate airport '{airport}' in manifest")
        seen_airports.add(airport)

        if not isinstance(entry, dict):
            raise ValueError(f"{manifest_path}: entry for airport '{airport}' must be an object")

        repo_path = ensure_text_field(entry.get("repo_path"), "repo_path", manifest_path)
        candidate = _safe_relative_path(repo_path, root)
        if not candidate.exists():
            raise ValueError(f"{manifest_path}: missing file for airport '{airport}' at '{repo_path}'")
        if not candidate.is_file():
            raise ValueError(f"{manifest_path}: repo_path for airport '{airport}' is not a file")

        generated_entry = validate_options_file(candidate, root)
        if str(generated_entry["airport"]) != airport:
            raise ValueError(
                f"{manifest_path}: airport key '{airport}' does not match file airport '{generated_entry['airport']}'"
            )

        expected_sha = str(entry.get("sha256", "")).strip().lower()
        expected_size = int(entry.get("size_bytes", -1))
        if expected_sha != str(generated_entry["sha256"]):
            raise ValueError(f"{manifest_path}: sha256 mismatch for airport '{airport}'")
        if expected_size != int(generated_entry["size_bytes"]):
            raise ValueError(f"{manifest_path}: size_bytes mismatch for airport '{airport}'")

    return len(seen_airports)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate procedure_options.json files and generate the community procedure-options manifest.")
    parser.add_argument("--write", action="store_true", help="Write .voiceatc/procedure_options_manifest.json")
    parser.add_argument("--validate-only", action="store_true", help="Validate source files and checked-in manifest entries")
    args = parser.parse_args()

    try:
        manifest = build_manifest()
        validated_entries = 0
        if args.validate_only:
            validated_entries = validate_existing_manifest_entries()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.write:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    elif args.validate_only:
        print(f"Validated {len(manifest['airports'])} procedure options files and {validated_entries} manifest entries.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
