#!/usr/bin/env python3
"""Validate community content placement against the canonical hierarchy registry."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "documentation" / "content_hierarchy.json"
AIRPORT_FILE_NAMES = {"runway_configs.json", "constraints.json", "procedure_options.json"}
TERMINAL_FILE_NAMES = {
    "mva.json",
    "misc_drawings.json",
    "sector_configs.json",
    "sector_definitions.json",
    "sector_influence.json",
}
PROFILE_FILE_NAMES = {"colors.json", "style.json"}
CONTENT_FILE_NAMES = AIRPORT_FILE_NAMES | TERMINAL_FILE_NAMES | PROFILE_FILE_NAMES
PLACEHOLDER_RE = re.compile(r"^[A-Z]{1,2}X{2,3}$")
AIRPORT_RE = re.compile(r"^[A-Z0-9]{4}$")
EXPECTED_US_COLOR_ALIASES = {f"K/K{chr(letter)}" for letter in range(ord("A"), ord("Z") + 1)}


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: registry must be a JSON object")
    return payload


def _registry_maps(registry: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, Any], dict[str, list[str]]]:
    nationalities = registry.get("nationality_areas", {})
    operational = registry.get("operational_areas", {})
    terminals = registry.get("terminal_scopes", {})
    if not isinstance(nationalities, dict) or not isinstance(operational, dict) or not isinstance(terminals, dict):
        raise ValueError("registry nationality_areas, operational_areas, and terminal_scopes must be objects")
    return nationalities, operational, terminals


def _parse_scope(scope: str, registry: dict[str, Any], *, allow_shallow: bool) -> tuple[str | None, list[str]]:
    nationalities, operational, _terminals = _registry_maps(registry)
    parts = scope.split("/") if scope else []
    errors: list[str] = []
    if not parts or any(not part for part in parts):
        return None, ["scope is empty or contains an empty segment"]
    for part in parts:
        if PLACEHOLDER_RE.fullmatch(part):
            errors.append(f"placeholder identifier '{part}' is prohibited")

    region = parts[0]
    if region not in nationalities:
        errors.append(f"unknown region '{region}'")
        return None, errors
    if len(parts) == 1:
        if allow_shallow:
            return None, errors
        errors.append("missing FIR/ARTCC layer")
        return None, errors

    all_nationalities = {area for areas in nationalities.values() for area in areas}
    operational_index = 1
    if parts[1] in all_nationalities:
        if parts[1] not in nationalities[region]:
            errors.append(f"nationality area '{parts[1]}' is not registered under region '{region}'")
        operational_index = 2
    if operational_index >= len(parts):
        if allow_shallow:
            return None, errors
        errors.append("missing FIR/ARTCC layer")
        return None, errors

    operational_ident = parts[operational_index]
    if operational_ident not in operational:
        errors.append(f"unknown operational identifier '{operational_ident}'")
    trailing = parts[operational_index + 1 :]
    if len(trailing) > 2:
        errors.append("more than one ACC grouping appears between FIR/ARTCC and terminal area")
    return operational_ident, errors


def _validate_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("schema_version") != 1:
        errors.append("registry: schema_version must be 1")
    authorities = registry.get("authorities", {})
    try:
        _nationalities, operational, terminals = _registry_maps(registry)
    except ValueError as exc:
        return errors + [f"registry: {exc}"]
    if not isinstance(authorities, dict):
        return errors + ["registry: authorities must be an object"]

    compatibility = registry.get("release_compatibility", {})
    if not isinstance(compatibility, dict):
        errors.append("registry: release_compatibility must be an object")
        compatibility = {}
    if compatibility.get("retention") != "until_explicit_deprecation":
        errors.append("registry: release compatibility retention must be 'until_explicit_deprecation'")
    alias_groups = compatibility.get("color_profile_aliases", {})
    if not isinstance(alias_groups, dict):
        errors.append("registry: release compatibility color_profile_aliases must be an object")
        alias_groups = {}
    seen_aliases: set[str] = set()
    for source_scope, aliases in alias_groups.items():
        if source_scope not in _nationalities or "/" in source_scope:
            errors.append(f"registry: compatibility source scope '{source_scope}' must be a registered region")
        if not isinstance(aliases, list):
            errors.append(f"registry: compatibility aliases for '{source_scope}' must be an array")
            continue
        for alias in aliases:
            if not isinstance(alias, str):
                errors.append(f"registry: compatibility alias '{alias}' must be a string")
                continue
            parts = alias.split("/")
            if len(parts) != 2 or parts[0] != source_scope or any(not part for part in parts):
                errors.append(f"registry: compatibility alias '{alias}' must be a two-segment child of '{source_scope}'")
            if alias in seen_aliases:
                errors.append(f"registry: duplicate compatibility alias '{alias}'")
            seen_aliases.add(alias)
    us_aliases = alias_groups.get("K")
    if isinstance(us_aliases, list) and set(us_aliases) != EXPECTED_US_COLOR_ALIASES:
        errors.append("registry: K color compatibility aliases must contain exactly K/KA through K/KZ")

    for ident, entry in operational.items():
        if PLACEHOLDER_RE.fullmatch(ident):
            errors.append(f"registry: placeholder operational identifier '{ident}' is prohibited")
        if not isinstance(entry, dict) or entry.get("authority") not in authorities:
            errors.append(f"registry: operational identifier '{ident}' has an unknown authority")
        if not isinstance(entry, dict) or entry.get("kind") not in {"fir", "artcc"}:
            errors.append(f"registry: operational identifier '{ident}' must have kind 'fir' or 'artcc'")

    airport_scopes: dict[str, str] = {}
    for scope, airports in terminals.items():
        _operational_ident, scope_errors = _parse_scope(scope, registry, allow_shallow=False)
        parts = scope.split("/")
        nationalities = registry.get("nationality_areas", {})
        all_nationalities = {area for areas in nationalities.values() for area in areas}
        operational_index = 2 if len(parts) > 1 and parts[1] in all_nationalities else 1
        trailing = parts[operational_index + 1 :] if len(parts) > operational_index else []
        if len(trailing) not in {1, 2}:
            scope_errors.append("terminal scope must end after an optional single ACC grouping and terminal area")
        for message in scope_errors:
            errors.append(f"registry terminal '{scope}': {message}")
        if not isinstance(airports, list):
            errors.append(f"registry terminal '{scope}': airports must be an array")
            continue
        for airport in airports:
            if not isinstance(airport, str) or not AIRPORT_RE.fullmatch(airport):
                errors.append(f"registry terminal '{scope}': invalid airport '{airport}'")
            elif airport in airport_scopes:
                errors.append(f"registry: airport '{airport}' is registered in both '{airport_scopes[airport]}' and '{scope}'")
            else:
                airport_scopes[airport] = scope
    return errors


def _airport_scope_map(registry: dict[str, Any]) -> dict[str, str]:
    _nationalities, _operational, terminals = _registry_maps(registry)
    return {airport: scope for scope, airports in terminals.items() for airport in airports}


def _airport_references(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    references: set[str] = set()

    def visit(value: object, key: str = "") -> None:
        if key in {"airport", "airport_icao", "icao"}:
            values = value if isinstance(value, list) else [value]
            references.update(item for item in values if isinstance(item, str) and AIRPORT_RE.fullmatch(item))
        elif key in {"airports", "airport_icaos"} and isinstance(value, list):
            references.update(item for item in value if isinstance(item, str) and AIRPORT_RE.fullmatch(item))
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    visit(payload)
    return references


def _validate_profile_scope(scope: str, registry: dict[str, Any]) -> list[str]:
    _operational_ident, errors = _parse_scope(scope, registry, allow_shallow=True)
    if errors:
        return errors
    nationalities, _operational, terminals = _registry_maps(registry)
    parts = scope.split("/")
    if len(parts) == 1 or (len(parts) == 2 and parts[1] in nationalities.get(parts[0], [])):
        return []
    if scope in terminals or any(candidate.startswith(scope + "/") for candidate in terminals):
        return []
    if any(candidate == scope for candidate in terminals):
        return []
    all_nationalities = {area for areas in nationalities.values() for area in areas}
    operational_index = 2 if len(parts) > 1 and parts[1] in all_nationalities else 1
    if len(parts) == operational_index + 1:
        return []
    return ["profile scope is not a registered FIR/ARTCC, ACC group, or terminal area"]


def _validate_content_file(path: Path, root: Path, registry: dict[str, Any]) -> list[str]:
    relative = path.relative_to(root).as_posix()
    errors: list[str] = []
    for part in Path(relative).parts:
        if PLACEHOLDER_RE.fullmatch(part):
            errors.append(f"placeholder identifier '{part}' is prohibited")

    if path.name in PROFILE_FILE_NAMES:
        scope = path.parent.relative_to(root).as_posix()
        errors.extend(_validate_profile_scope(scope, registry))
        return [f"{relative}: {message}" for message in dict.fromkeys(errors)]

    _nationalities, _operational, terminals = _registry_maps(registry)
    airport_scopes = _airport_scope_map(registry)
    if path.name in AIRPORT_FILE_NAMES:
        airport = path.parent.name
        scope = path.parent.parent.relative_to(root).as_posix()
        _ident, scope_errors = _parse_scope(scope, registry, allow_shallow=False)
        errors.extend(scope_errors)
        if scope not in terminals:
            registered_scope = airport_scopes.get(airport)
            if registered_scope:
                errors.append(f"airport '{airport}' belongs in terminal scope '{registered_scope}', not '{scope}'")
            else:
                errors.append(f"airport file is outside a registered terminal scope '{scope}'")
        elif airport not in terminals[scope]:
            errors.append(f"airport '{airport}' is not registered in terminal scope '{scope}'")
        for referenced in _airport_references(path):
            if referenced != airport:
                errors.append(f"payload airport '{referenced}' does not match folder airport '{airport}'")
    else:
        scope = path.parent.relative_to(root).as_posix()
        _ident, scope_errors = _parse_scope(scope, registry, allow_shallow=False)
        errors.extend(scope_errors)
        parent_scope = path.parent.parent.relative_to(root).as_posix() if path.parent != root else ""
        if parent_scope in terminals and path.parent.name in terminals[parent_scope]:
            errors.append("terminal-area file must not be inside an airport folder")
        elif scope not in terminals:
            errors.append(f"terminal-area file is outside a registered terminal scope '{scope}'")
        for airport in _airport_references(path):
            registered_scope = airport_scopes.get(airport)
            if registered_scope is None:
                errors.append(f"referenced airport '{airport}' is not registered")
            elif registered_scope != scope:
                errors.append(f"referenced airport '{airport}' belongs in terminal scope '{registered_scope}', not '{scope}'")

    return [f"{relative}: {message}" for message in dict.fromkeys(errors)]


def validate_repository(root: Path = ROOT, registry_path: Path | None = None) -> list[str]:
    registry = load_registry(registry_path or (root / "documentation" / "content_hierarchy.json"))
    errors = _validate_registry(registry)
    ignored_parts = {".git", ".voiceatc", "node_modules"}
    paths = sorted(
        path
        for path in root.rglob("*.json")
        if path.name in CONTENT_FILE_NAMES and not ignored_parts.intersection(path.parts)
    )
    for path in paths:
        errors.extend(_validate_content_file(path, root, registry))
    compatibility = registry.get("release_compatibility", {})
    alias_groups = compatibility.get("color_profile_aliases", {}) if isinstance(compatibility, dict) else {}
    if isinstance(alias_groups, dict):
        for source_scope, aliases in alias_groups.items():
            if not (root / str(source_scope) / "colors.json").is_file():
                errors.append(f"release compatibility source '{source_scope}' is missing colors.json")
            if not isinstance(aliases, list):
                continue
            for alias in aliases:
                alias_path = root / str(alias)
                for file_name in PROFILE_FILE_NAMES:
                    if (alias_path / file_name).exists():
                        errors.append(f"release-only compatibility alias must not exist in source: {alias}/{file_name}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="validate the repository without writing files")
    args = parser.parse_args()
    if not args.validate_only:
        parser.error("--validate-only is required; this tool never rewrites content")
    try:
        errors = validate_repository()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Content hierarchy validation failed: {exc}") from exc
    if errors:
        raise SystemExit("Content hierarchy validation failed:\n- " + "\n- ".join(errors))
    print("Content hierarchy validation passed.")


if __name__ == "__main__":
    main()
