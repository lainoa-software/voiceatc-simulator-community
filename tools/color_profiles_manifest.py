#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
BRANCH_NAME = "main"
SCHEMA_VERSION = 1
PROFILE_FILE_NAMES = {
    "colors": "colors.json",
    "style": "style.json",
}
FILE_KIND_BY_NAME = {file_name: kind for kind, file_name in PROFILE_FILE_NAMES.items()}
FILE_KIND_ORDER = ("colors", "style")
ALLOWED_SCOPE_DEPTHS = {1, 2, 3, 4, 5}
LEGACY_ALLOWED_SCOPE_DEPTHS = {2, 3, 4, 5}
HIERARCHY_REGISTRY_PATH = Path("documentation") / "content_hierarchy.json"
EXPECTED_US_RELEASE_ALIASES = {f"K/K{chr(letter)}" for letter in range(ord("A"), ord("Z") + 1)}
HEX_COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$")
ALLOWED_NUMERIC_KEYS = {"symbol_size", "traildot_size", "symbol_line_width"}


def _tracked_profile_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for file_name in PROFILE_FILE_NAMES.values():
        paths.extend(
            path
            for path in root.rglob(file_name)
            if ".git" not in path.parts and ".voiceatc" not in path.parts
        )
    return sorted(paths)


def safe_repo_path(path: Path, root: Path = ROOT) -> str:
    repo_path = path.relative_to(root).as_posix()
    if not repo_path or repo_path.startswith("/") or repo_path.startswith("../") or "/../" in repo_path:
        raise ValueError(f"unsafe repo path '{repo_path}'")
    return repo_path


def _load_json_object(path: Path) -> tuple[dict[str, object], bytes]:
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: color profile file must be a JSON object")
    return payload, raw_bytes


def _validate_scope_depth(scope_path: str, path: Path) -> None:
    depth = len([part for part in scope_path.split("/") if part])
    if depth not in ALLOWED_SCOPE_DEPTHS:
        raise ValueError(f"{path}: scope depth must be 1, 2, 3, 4, or 5 segments")


def _validate_hex_color(value: object, key: str, path: Path) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{path}: '{key}' must be a string")
    if not HEX_COLOR_RE.fullmatch(value.strip()):
        raise ValueError(f"{path}: '{key}' must be a 6 or 8 digit hex color")


def validate_colors_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    if not payload:
        raise ValueError(f"{path}: colors.json must not be empty")

    for key, value in payload.items():
        if not isinstance(key, str) or not key.endswith("_color"):
            raise ValueError(f"{path}: colors.json only accepts top-level '*_color' keys")
        _validate_hex_color(value, key, path)

    return {
        "repo_path": safe_repo_path(path, root),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def validate_style_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    if not payload:
        raise ValueError(f"{path}: style.json must not be empty")

    for key, value in payload.items():
        if key == "defined_symbols":
            if not isinstance(value, dict) or not value:
                raise ValueError(f"{path}: 'defined_symbols' must be a non-empty object")
            for symbol_name, symbol_def in value.items():
                if not isinstance(symbol_name, str) or not symbol_name.strip():
                    raise ValueError(f"{path}: defined_symbols keys must be non-empty strings")
                if isinstance(symbol_def, str):
                    raise ValueError(
                        f"{path}: defined_symbols['{symbol_name}'] uses legacy bitmap format; "
                        f"convert to dict with 'type', 'draw', and 'connection_points'"
                    )
                elif isinstance(symbol_def, dict):
                    for required in ("type", "draw", "connection_points"):
                        if required not in symbol_def:
                            raise ValueError(f"{path}: defined_symbols['{symbol_name}'] missing required key '{required}'")
                    if not isinstance(symbol_def["type"], str) or not symbol_def["type"].strip():
                        raise ValueError(f"{path}: defined_symbols['{symbol_name}']['type'] must be a non-empty string")
                    if not isinstance(symbol_def["draw"], str) or not symbol_def["draw"].strip():
                        raise ValueError(f"{path}: defined_symbols['{symbol_name}']['draw'] must be a non-empty string")
                    if not isinstance(symbol_def["connection_points"], list):
                        raise ValueError(f"{path}: defined_symbols['{symbol_name}']['connection_points'] must be an array")
                    if "height" in symbol_def:
                        height = symbol_def["height"]
                        if (
                            isinstance(height, bool)
                            or not isinstance(height, (int, float))
                            or not math.isfinite(float(height))
                            or height <= 0
                        ):
                            raise ValueError(
                                f"{path}: defined_symbols['{symbol_name}']['height'] "
                                "must be a finite positive number"
                            )
                else:
                    raise ValueError(f"{path}: defined_symbols['{symbol_name}'] must be an object with 'type', 'draw', and 'connection_points'")
            continue
        if key in ALLOWED_NUMERIC_KEYS:
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{path}: '{key}' must be a positive number")
            continue
        if key == "label":
            if not isinstance(value, dict) or not value:
                raise ValueError(f"{path}: 'label' must be a non-empty object")
            continue
        if not isinstance(key, str) or not key.endswith("_symbol"):
            raise ValueError(f"{path}: style.json only accepts 'defined_symbols', 'label', '*_symbol', and numeric config keys")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}: '{key}' must be a non-empty string")

    return {
        "repo_path": safe_repo_path(path, root),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def validate_profile_directory(profile_dir: Path, profile_files: dict[str, Path], root: Path = ROOT) -> dict[str, object]:
    scope_path = safe_repo_path(profile_dir, root)
    _validate_scope_depth(scope_path, profile_dir)

    if "colors" not in profile_files:
        raise ValueError(f"{scope_path}: missing color profile files: colors")

    files: dict[str, object] = {
        "colors": validate_colors_file(profile_files["colors"], root),
    }
    if "style" in profile_files:
        files["style"] = validate_style_file(profile_files["style"], root)
    return {
        "scope_path": scope_path,
        "files": files,
    }


def current_commit_sha(root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()


def build_manifest(root: Path = ROOT, commit_sha: str | None = None) -> dict[str, object]:
    profile_candidates: dict[Path, dict[str, Path]] = {}
    for path in _tracked_profile_files(root):
        kind = FILE_KIND_BY_NAME.get(path.name)
        if kind is None:
            continue
        profile_candidates.setdefault(path.parent, {})[kind] = path

    profiles: dict[str, dict[str, object]] = {}
    for profile_dir in sorted(profile_candidates):
        validated_profile = validate_profile_directory(profile_dir, profile_candidates[profile_dir], root)
        scope_path = str(validated_profile["scope_path"])
        if scope_path in profiles:
            raise ValueError(f"duplicate color profile scope '{scope_path}'")
        profiles[scope_path] = {"files": validated_profile["files"]}

    return {
        "schema_version": SCHEMA_VERSION,
        "repo": REPO_NAME,
        "branch": BRANCH_NAME,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_sha": commit_sha if commit_sha is not None else current_commit_sha(root),
        "profiles": dict(sorted(profiles.items())),
    }


def _release_alias_groups(root: Path) -> dict[str, list[str]]:
    registry_path = root / HIERARCHY_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError(f"{registry_path}: hierarchy registry must be an object")
    nationality_areas = registry.get("nationality_areas", {})
    if not isinstance(nationality_areas, dict):
        raise ValueError(f"{registry_path}: nationality_areas must be an object")
    compatibility = registry.get("release_compatibility", {})
    if not isinstance(compatibility, dict):
        raise ValueError(f"{registry_path}: release_compatibility must be an object")
    if compatibility.get("retention") != "until_explicit_deprecation":
        raise ValueError(f"{registry_path}: release compatibility retention must be 'until_explicit_deprecation'")
    alias_groups_variant = compatibility.get("color_profile_aliases", {})
    if not isinstance(alias_groups_variant, dict):
        raise ValueError(f"{registry_path}: color_profile_aliases must be an object")

    result: dict[str, list[str]] = {}
    seen_aliases: set[str] = set()
    for source_scope, aliases_variant in alias_groups_variant.items():
        if source_scope not in nationality_areas or "/" in source_scope:
            raise ValueError(f"{registry_path}: release alias source '{source_scope}' must be a registered region scope")
        if not isinstance(aliases_variant, list) or not aliases_variant:
            raise ValueError(f"{registry_path}: release aliases for '{source_scope}' must be a non-empty array")
        aliases: list[str] = []
        for alias_variant in aliases_variant:
            if not isinstance(alias_variant, str):
                raise ValueError(f"{registry_path}: legacy color alias '{alias_variant}' must be a string")
            alias = alias_variant.strip().replace("\\", "/")
            parts = alias.split("/")
            if len(parts) != 2 or parts[0] != source_scope or any(not part for part in parts):
                raise ValueError(f"{registry_path}: unsafe legacy color alias '{alias}'")
            if alias in seen_aliases:
                raise ValueError(f"{registry_path}: duplicate legacy color alias '{alias}'")
            seen_aliases.add(alias)
            aliases.append(alias)
        result[source_scope] = sorted(aliases)
    if "K" in result and set(result["K"]) != EXPECTED_US_RELEASE_ALIASES:
        raise ValueError(f"{registry_path}: K release aliases must contain exactly K/KA through K/KZ")
    return result


def _validate_release_projection(profiles: dict[str, object], archive_sources: dict[str, str]) -> None:
    expected_archive_paths: set[str] = set()
    for scope_path, profile_variant in profiles.items():
        depth = len([part for part in scope_path.split("/") if part])
        if depth not in LEGACY_ALLOWED_SCOPE_DEPTHS:
            raise ValueError(f"release color scope '{scope_path}' is incompatible with legacy clients")
        if not isinstance(profile_variant, dict) or not isinstance(profile_variant.get("files"), dict):
            raise ValueError(f"release color scope '{scope_path}' has invalid files")
        files = profile_variant["files"]
        if "colors" not in files:
            raise ValueError(f"release color scope '{scope_path}' is missing colors")
        for kind, file_variant in files.items():
            if kind not in PROFILE_FILE_NAMES or not isinstance(file_variant, dict):
                raise ValueError(f"release color scope '{scope_path}' has invalid file kind '{kind}'")
            expected_repo_path = f"{scope_path}/{PROFILE_FILE_NAMES[kind]}"
            if file_variant.get("repo_path") != expected_repo_path:
                raise ValueError(f"release color scope '{scope_path}' has mismatched {kind} repo_path")
            expected_archive_paths.add(expected_repo_path)
    if expected_archive_paths != set(archive_sources):
        raise ValueError("release color manifest paths do not match archive source mappings")


def build_release_projection(root: Path = ROOT, commit_sha: str | None = None) -> dict[str, object]:
    source_manifest = build_manifest(root, commit_sha=commit_sha)
    source_profiles = source_manifest["profiles"]
    alias_groups = _release_alias_groups(root)
    missing_sources = set(alias_groups) - set(source_profiles)
    if missing_sources:
        raise ValueError(f"release color aliases reference missing source scopes: {sorted(missing_sources)}")

    profiles: dict[str, object] = {}
    archive_sources: dict[str, str] = {}
    for source_scope, profile_variant in source_profiles.items():
        if not isinstance(profile_variant, dict) or not isinstance(profile_variant.get("files"), dict):
            raise ValueError(f"source color scope '{source_scope}' has invalid files")
        files = profile_variant["files"]
        aliases = alias_groups.get(source_scope)
        if aliases is None:
            if len(source_scope.split("/")) == 1:
                raise ValueError(f"region color scope '{source_scope}' requires declared legacy release aliases")
            profiles[source_scope] = {"files": {kind: dict(entry) for kind, entry in files.items()}}
            for entry in files.values():
                repo_path = str(entry["repo_path"])
                if repo_path in archive_sources:
                    raise ValueError(f"duplicate release archive path '{repo_path}'")
                archive_sources[repo_path] = repo_path
            continue

        for alias in aliases:
            if alias in source_profiles or alias in profiles:
                raise ValueError(f"release color alias collides with source scope '{alias}'")
            alias_files: dict[str, object] = {}
            for kind, entry in files.items():
                archive_path = f"{alias}/{PROFILE_FILE_NAMES[kind]}"
                source_path = str(entry["repo_path"])
                if archive_path in archive_sources:
                    raise ValueError(f"duplicate release archive path '{archive_path}'")
                if (root / archive_path).exists():
                    raise ValueError(f"release-only color alias exists in canonical source: '{archive_path}'")
                alias_entry = dict(entry)
                alias_entry["repo_path"] = archive_path
                alias_files[kind] = alias_entry
                archive_sources[archive_path] = source_path
            profiles[alias] = {"files": alias_files}

    sorted_profiles = dict(sorted(profiles.items()))
    sorted_archive_sources = dict(sorted(archive_sources.items()))
    _validate_release_projection(sorted_profiles, sorted_archive_sources)
    return {
        "profiles": sorted_profiles,
        "archive_sources": sorted_archive_sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate split color profiles and generate the community color-profiles manifest.")
    parser.add_argument("--write", action="store_true", help="Deprecated; release-backed manifests are publication-owned")
    parser.add_argument("--validate-only", action="store_true", help="Validate only, without writing the manifest")
    args = parser.parse_args()

    if args.write:
        print(
            "Refusing to write the release-backed color manifest directly; "
            "use community_release_manifest.py during publication.",
            file=sys.stderr,
        )
        return 1

    try:
        manifest = build_manifest()
        release_projection = build_release_projection()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.validate_only:
        print(
            f"Validated {len(manifest['profiles'])} canonical color profiles and "
            f"{len(release_projection['profiles'])} legacy-compatible release profiles."
        )
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
