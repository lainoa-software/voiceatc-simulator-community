#!/usr/bin/env python3
"""Validate community content placement against the canonical hierarchy registry."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, NamedTuple


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_RELATIVE = "documentation/content_hierarchy.json"
REGISTRY_PATH = ROOT / REGISTRY_RELATIVE
AIRPORT_FILE_NAMES = {
    "runway_configs.json",
    "constraints.json",
    "procedure_options.json",
    "visual_procedures.json",
    "visual_go_arounds.json",
    "visual_sight_references.json",
}
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
NATIONALITY_AREA_RE = re.compile(r"^[A-Z]{2}$")
EXPECTED_US_COLOR_ALIASES = {f"K/K{chr(letter)}" for letter in range(ord("A"), ord("Z") + 1)}
UNREGISTERED_SCOPE = "unregistered_scope"
PRINT_WIDTH = 80


class Finding(NamedTuple):
    """One problem, carrying enough structure to group related ones in the report.

    A new terminal area trips one rule but many files, so those findings are
    tagged with the scope they share and reported once with the line to add.
    """

    message: str
    relative: str = ""
    kind: str = "generic"
    scope: str = ""
    airport: str = ""

    def format(self) -> str:
        return f"{self.relative}: {self.message}" if self.relative else self.message


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

    # A nationality area is the first two letters of its FIR code, so its first
    # letter is the region. Registering it anywhere else makes the registry agree
    # with a misfiled folder instead of catching it: France, Greece, Italy,
    # Austria, Portugal and Switzerland sat under 'E' that way for a month.
    for region, areas in _nationalities.items():
        if not isinstance(areas, list):
            errors.append(f"registry: nationality areas for region '{region}' must be an array")
            continue
        for area in areas:
            if not isinstance(area, str) or not NATIONALITY_AREA_RE.fullmatch(area):
                errors.append(f"registry: nationality area '{area}' must be two uppercase letters")
                continue
            if not area.startswith(region):
                errors.append(
                    f"registry: nationality area '{area}' belongs under region '{area[0]}', not '{region}'"
                )

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


def _dedupe(findings: list[Finding]) -> list[Finding]:
    unique: dict[str, Finding] = {}
    for finding in findings:
        unique.setdefault(finding.message, finding)
    return list(unique.values())


def _validate_content_file(path: Path, root: Path, registry: dict[str, Any]) -> list[Finding]:
    relative = path.relative_to(root).as_posix()
    findings: list[Finding] = []

    def add(message: str, *, kind: str = "generic", scope: str = "", airport: str = "") -> None:
        findings.append(Finding(message, relative, kind, scope, airport))

    for part in Path(relative).parts:
        if PLACEHOLDER_RE.fullmatch(part):
            add(f"placeholder identifier '{part}' is prohibited")

    if path.name in PROFILE_FILE_NAMES:
        scope = path.parent.relative_to(root).as_posix()
        for message in _validate_profile_scope(scope, registry):
            add(message)
        return _dedupe(findings)

    _nationalities, _operational, terminals = _registry_maps(registry)
    airport_scopes = _airport_scope_map(registry)
    if path.name in AIRPORT_FILE_NAMES:
        airport = path.parent.name
        scope = path.parent.parent.relative_to(root).as_posix()
        _ident, scope_errors = _parse_scope(scope, registry, allow_shallow=False)
        for message in scope_errors:
            add(message)
        if scope not in terminals:
            registered_scope = airport_scopes.get(airport)
            if registered_scope:
                add(f"airport '{airport}' belongs in terminal scope '{registered_scope}', not '{scope}'")
            else:
                add(
                    f"airport file is outside a registered terminal scope '{scope}'",
                    kind=UNREGISTERED_SCOPE,
                    scope=scope,
                    airport=airport,
                )
        elif airport not in terminals[scope]:
            add(f"airport '{airport}' is not registered in terminal scope '{scope}'")
        for referenced in _airport_references(path):
            if referenced != airport:
                add(f"payload airport '{referenced}' does not match folder airport '{airport}'")
    else:
        scope = path.parent.relative_to(root).as_posix()
        _ident, scope_errors = _parse_scope(scope, registry, allow_shallow=False)
        for message in scope_errors:
            add(message)
        parent_scope = path.parent.parent.relative_to(root).as_posix() if path.parent != root else ""
        inside_airport_folder = parent_scope in terminals and path.parent.name in terminals[parent_scope]
        # Only an unregistered terminal area is groupable. A misplaced file inside
        # an airport folder needs moving, not registering.
        groupable_scope = "" if inside_airport_folder or scope in terminals else scope
        if inside_airport_folder:
            add("terminal-area file must not be inside an airport folder")
        elif groupable_scope:
            add(
                f"terminal-area file is outside a registered terminal scope '{scope}'",
                kind=UNREGISTERED_SCOPE,
                scope=scope,
            )
        for airport in _airport_references(path):
            registered_scope = airport_scopes.get(airport)
            if registered_scope is None:
                add(
                    f"referenced airport '{airport}' is not registered",
                    kind=UNREGISTERED_SCOPE if groupable_scope else "generic",
                    scope=groupable_scope,
                    airport=airport,
                )
            elif registered_scope != scope:
                add(f"referenced airport '{airport}' belongs in terminal scope '{registered_scope}', not '{scope}'")

    return _dedupe(findings)


def collect_findings(root: Path = ROOT, registry_path: Path | None = None) -> list[Finding]:
    registry = load_registry(registry_path or (root / REGISTRY_RELATIVE))
    findings = [Finding(message) for message in _validate_registry(registry)]
    ignored_parts = {".git", ".voiceatc", "node_modules"}
    paths = sorted(
        path
        for path in root.rglob("*.json")
        if path.name in CONTENT_FILE_NAMES and not ignored_parts.intersection(path.parts)
    )
    for path in paths:
        findings.extend(_validate_content_file(path, root, registry))
    compatibility = registry.get("release_compatibility", {})
    alias_groups = compatibility.get("color_profile_aliases", {}) if isinstance(compatibility, dict) else {}
    if isinstance(alias_groups, dict):
        for source_scope, aliases in alias_groups.items():
            if not (root / str(source_scope) / "colors.json").is_file():
                findings.append(Finding(f"release compatibility source '{source_scope}' is missing colors.json"))
            if not isinstance(aliases, list):
                continue
            for alias in aliases:
                alias_path = root / str(alias)
                for file_name in PROFILE_FILE_NAMES:
                    if (alias_path / file_name).exists():
                        findings.append(
                            Finding(f"release-only compatibility alias must not exist in source: {alias}/{file_name}")
                        )
    return findings


def validate_repository(root: Path = ROOT, registry_path: Path | None = None) -> list[str]:
    return [finding.format() for finding in collect_findings(root, registry_path)]


def render_scope_entry(scope: str, airports: list[str], indent: int = 4, *, comma: bool = False) -> list[str]:
    """Render one terminal_scopes entry the way prettier formats this file.

    Arrays stay on one line until the line would exceed prettier's print width,
    so a rewritten block is byte-identical to what `npm run format:json` emits.
    """
    pad = " " * indent
    tail = "," if comma else ""
    inline = f'{pad}"{scope}": [' + ", ".join(f'"{airport}"' for airport in airports) + f"]{tail}"
    if len(inline) <= PRINT_WIDTH:
        return [inline]
    lines = [f'{pad}"{scope}": [']
    for position, airport in enumerate(airports):
        separator = "," if position < len(airports) - 1 else ""
        lines.append(f'{" " * (indent + 2)}"{airport}"{separator}')
    lines.append(f"{pad}]{tail}")
    return lines


def format_report(findings: list[Finding]) -> str:
    """Collapse the unregistered-scope family into one remedy block per scope."""
    scope_airports: dict[str, set[str]] = {}
    scope_files: dict[str, set[str]] = {}
    remaining: list[Finding] = []
    for finding in findings:
        if finding.kind == UNREGISTERED_SCOPE and finding.scope:
            scope_airports.setdefault(finding.scope, set())
            scope_files.setdefault(finding.scope, set()).add(finding.relative)
            if finding.airport:
                scope_airports[finding.scope].add(finding.airport)
        else:
            remaining.append(finding)

    blocks: list[str] = []
    for scope in sorted(scope_airports):
        airports = sorted(scope_airports[scope])
        count = len(scope_files[scope])
        entry = "\n".join(render_scope_entry(scope, airports, 6, comma=True))
        blocks.append(
            f"{scope} is not a registered terminal scope "
            f"({count} file{'' if count == 1 else 's'} affected).\n"
            f'  Add this entry to {REGISTRY_RELATIVE} under "terminal_scopes":\n'
            f"{entry}\n"
            f"  Or run: python tools/content_hierarchy.py --register {scope}"
        )
    if remaining:
        blocks.append("\n".join(f"- {finding.format()}" for finding in remaining))
    return "\n\n".join(blocks)


def _insertion_index(ordered: list[str], scope: str) -> int:
    """Position `scope` after the last entry sharing the most leading path segments."""
    target = scope.split("/")
    best_shared = 0
    best_index = len(ordered)
    for index, existing in enumerate(ordered):
        parts = existing.split("/")
        shared = 0
        for left, right in zip(target, parts):
            if left != right:
                break
            shared += 1
        if shared >= best_shared and shared > 0:
            best_shared = shared
            best_index = index + 1
    return best_index


def register_scope(scope: str, root: Path = ROOT) -> str:
    """Register a terminal scope, or add newly created airport folders to one already registered."""
    registry_path = root / REGISTRY_RELATIVE
    registry = load_registry(registry_path)
    _nationalities, _operational, terminals = _registry_maps(registry)
    known = scope in terminals
    _ident, scope_errors = _parse_scope(scope, registry, allow_shallow=False)
    if scope_errors:
        raise SystemExit(f"Cannot register '{scope}':\n- " + "\n- ".join(scope_errors))
    directory = root / scope
    if not directory.is_dir():
        raise SystemExit(f"Cannot register '{scope}': {directory} does not exist")
    airports = sorted(
        child.name for child in directory.iterdir() if child.is_dir() and AIRPORT_RE.fullmatch(child.name)
    )
    if not airports:
        raise SystemExit(f"Cannot register '{scope}': it contains no airport folders")

    # An airport may be registered without a folder of its own — terminal-level data
    # can name it — so add what is on disk and never drop what is already listed.
    existing = list(terminals.get(scope, ()))
    added = [airport for airport in airports if airport not in existing]
    if known and not added:
        return f"'{scope}' is already registered with {', '.join(existing)}."
    entry = existing + added

    text = registry_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    start = next((index for index, line in enumerate(lines) if '"terminal_scopes"' in line), None)
    key_indent = 0 if start is None else len(lines[start]) - len(lines[start].lstrip())
    end = (
        None
        if start is None
        else next(
            (index for index in range(start + 1, len(lines)) if lines[index].startswith(" " * key_indent + "}")),
            None,
        )
    )
    if start is None or end is None:
        raise SystemExit(
            f"Cannot edit {REGISTRY_RELATIVE}: its terminal_scopes block is not in the expected "
            "layout. Run `npm run format:json` and try again."
        )

    # The registry is not stored in sorted order, so keep the existing sequence and
    # slot a new scope beside its closest relative. That keeps the diff to one line.
    ordered = list(terminals)
    if not known:
        ordered.insert(_insertion_index(ordered, scope), scope)
    merged = dict(terminals)
    merged[scope] = entry
    body: list[str] = []
    for position, key in enumerate(ordered):
        body.extend(
            render_scope_entry(key, list(merged[key]), key_indent + 2, comma=position < len(ordered) - 1)
        )
    # .gitattributes pins the working tree to LF; write_text would emit CRLF on Windows.
    registry_path.write_text("\n".join(lines[: start + 1] + body + lines[end:]), encoding="utf-8", newline="\n")
    if known:
        return f'Added {", ".join(added)} to "{scope}" in {REGISTRY_RELATIVE}.'
    return f'Registered "{scope}": [{", ".join(entry)}] in {REGISTRY_RELATIVE}.'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="validate the repository without writing files")
    parser.add_argument(
        "--register",
        metavar="SCOPE",
        help="add SCOPE to the registry with the airport folders it already contains",
    )
    args = parser.parse_args()
    if not args.validate_only and not args.register:
        parser.error("--validate-only or --register is required; this tool never rewrites content files")
    try:
        if args.register:
            print(register_scope(args.register))
        findings = collect_findings()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Content hierarchy validation failed: {exc}") from exc
    if findings:
        raise SystemExit("Content hierarchy validation failed:\n" + format_report(findings))
    print("Content hierarchy validation passed.")


if __name__ == "__main__":
    main()
