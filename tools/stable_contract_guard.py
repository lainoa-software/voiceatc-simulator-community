#!/usr/bin/env python3
"""Prove every default manifest and zip still parses in the oldest live game build.

The default paths (``.voiceatc/<dataset>_manifest.json`` and the release zips)
are read by every live build, including stable 0.6.1.24, which fails a whole
dataset on an unexpected zip entry or an unknown file kind. This guard replays
those rules, taken from the game repo at stable 0.6.1.24 (commit 88d8b09cd:
``autoloads/*_package.gd``, ``color_profile_contract.gd``, ``sector_data_contract.gd``,
``scripts/core/community_sync_io.gd``) and, for the visual syncs that stable
does not have, open beta 0.6.2.204 (commit 08523f152, exact-key manifests).

It is deliberately stricter than the old builds in one way: the top-level and
entry key sets must be exactly today's, so nothing new ever reaches a default
path. New fields and kinds belong in the full manifests (``.voiceatc/full/``).
The ``schema_version`` values checked here are frozen labels (``tools/legacy_contract.py``);
this guard keeps its own copy on purpose so a producer change cannot move both.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
HEADER_KEYS = {
    "schema_version",
    "repo",
    "release_tag",
    "commit_sha",
    "asset_name",
    "download_url",
    "sha256",
    "size_bytes",
    "published_at",
}
FILE_ENTRY_KEYS = {"repo_path", "sha256", "size_bytes"}
ZIP_DATASETS: dict[str, dict[str, object]] = {
    "mva": {
        "asset_key": "mva_zip",
        "count": "airport_count",
        "container": "airports",
        "suffixes": ("/mva.json",),
    },
    "runway_configs": {
        "asset_key": "runway_configs_zip",
        "count": "airport_count",
        "container": "airports",
        "suffixes": ("/runway_config.json", "/runway_configs.json"),
    },
    "misc_drawings": {
        "asset_key": "misc_drawings_zip",
        "count": "airport_count",
        "container": "airports",
        "suffixes": ("/misc_drawings.json",),
    },
    "sector_data": {
        "asset_key": "sector_data_zip",
        "count": "bundle_count",
        "container": "bundles",
        "kinds": {
            "configs": "sector_configs.json",
            "definitions": "sector_definitions.json",
            "influence": "sector_influence.json",
        },
        "required": ("configs", "definitions", "influence"),
    },
    "color_profiles": {
        "asset_key": "color_profiles_zip",
        "count": "profile_count",
        "container": "profiles",
        "kinds": {"colors": "colors.json", "style": "style.json"},
        "required": ("colors",),
        "max_depth": 5,
    },
}
FILE_MANIFESTS: dict[str, dict[str, object]] = {
    "constraints": {"suffix": ".json", "exact_keys": False},
    "procedure_options": {"suffix": ".json", "exact_keys": False},
    "visual_procedures": {
        "suffix": "/visual_procedures.json",
        "exact_keys": True,
        "icao": re.compile(r"^[A-Z]{4}$"),
        "max_bytes": 256 * 1024,
    },
    "visual_go_arounds": {
        "suffix": "/visual_go_arounds.json",
        "exact_keys": True,
        "icao": re.compile(r"^[A-Z]{4}$"),
        "max_bytes": 128 * 1024,
    },
    "visual_sight_references": {
        "suffix": "/visual_sight_references.json",
        "exact_keys": True,
        "icao": re.compile(r"^[A-Z0-9_]{4}$"),
        "max_bytes": 128 * 1024,
    },
}
FILE_MANIFEST_KEYS = {"schema_version", "repo", "published_at", "airports"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
# Gated route overlays and their full-feed tables never appear in the default feed.
FULL_ROUTES_PATH = "ROUTES/full/"
FULL_ROUTES_ASSET_RE = re.compile(r"routes[a-z_-]*-\d{4}-full\b")
DEFAULT_ROUTES_FILES = {
    "routes": Path(".voiceatc") / "routes_manifest.json",
    "release": Path(".voiceatc") / "release_manifest.json",
    "routes_default": Path("ROUTES") / "routes_default_manifest.json",
    "player_routes": Path(".voiceatc") / "player_routes_manifest.json",
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_safe_archive_path(path: str) -> bool:
    """``community_sync_io.gd`` is_safe_archive_path at 0.6.1.24."""
    normalized = path.replace("\\", "/").strip()
    return bool(normalized) and not (
        normalized.startswith("/")
        or normalized.startswith("../")
        or "/../" in normalized
        or ":" in normalized
        or normalized.endswith("/")
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_file_entry(where: str, entry: object, errors: list[str]) -> str:
    if not isinstance(entry, dict):
        errors.append(f"{where}: entry must be an object")
        return ""
    if set(entry) != FILE_ENTRY_KEYS:
        errors.append(f"{where}: entry keys {sorted(entry)} are not exactly {sorted(FILE_ENTRY_KEYS)}")
    repo_path = str(entry.get("repo_path", "")).strip()
    if not is_safe_archive_path(repo_path):
        errors.append(f"{where}: unsafe repo_path '{repo_path}'")
    if not str(entry.get("sha256", "")).strip():
        errors.append(f"{where}: empty sha256")
    if not _is_int(entry.get("size_bytes")) or int(entry["size_bytes"]) < 0:
        errors.append(f"{where}: size_bytes must be a whole number >= 0")
    return repo_path


def _check_header(dataset: str, manifest: dict[str, object], rules: dict[str, object], errors: list[str]) -> None:
    expected = HEADER_KEYS | {str(rules["count"]), str(rules["container"])}
    if set(manifest) != expected:
        errors.append(f"{dataset}: top-level keys {sorted(manifest)} are not exactly {sorted(expected)}")
    if manifest.get("schema_version") != 2 or isinstance(manifest.get("schema_version"), bool):
        errors.append(f"{dataset}: schema_version must be 2")
    if str(manifest.get("repo", "")).strip() != REPO_NAME:
        errors.append(f"{dataset}: repo must be {REPO_NAME}")
    for key in ("release_tag", "commit_sha", "asset_name", "sha256"):
        if not str(manifest.get(key, "")).strip():
            errors.append(f"{dataset}: {key} must not be empty")
    if not str(manifest.get("asset_name", "")).strip().endswith(".zip"):
        errors.append(f"{dataset}: asset_name must end with .zip")
    if not str(manifest.get("download_url", "")).strip().startswith("https://"):
        errors.append(f"{dataset}: download_url must start with https://")
    if not _is_int(manifest.get("size_bytes")) or int(manifest["size_bytes"]) <= 0:
        errors.append(f"{dataset}: size_bytes must be > 0")
    container = manifest.get(str(rules["container"]))
    count = manifest.get(str(rules["count"]))
    if not isinstance(container, dict):
        errors.append(f"{dataset}: {rules['container']} must be an object")
    elif not _is_int(count) or count != len(container):
        errors.append(f"{dataset}: {rules['count']} must equal the number of {rules['container']}")


def _expected_files(dataset: str, manifest: dict[str, object], rules: dict[str, object], errors: list[str]) -> dict[str, dict]:
    """Allowed zip names and their entries, as the old parser builds them."""
    expected: dict[str, dict] = {}
    container = manifest.get(str(rules["container"]))
    if not isinstance(container, dict):
        return expected
    seen_keys: set[str] = set()
    for key, entry in container.items():
        where = f"{dataset}: '{key}'"
        normalized_key = str(key).strip()
        if "kinds" not in rules:
            normalized_key = normalized_key.upper()
        if not normalized_key or normalized_key in seen_keys:
            errors.append(f"{where}: empty or duplicate key")
        seen_keys.add(normalized_key)
        if "kinds" in rules:
            if not is_safe_archive_path(normalized_key):
                errors.append(f"{where}: unsafe key")
            depth = len([part for part in normalized_key.split("/") if part])
            if "max_depth" in rules and not 1 <= depth <= int(rules["max_depth"]):
                errors.append(f"{where}: scope depth {depth} outside 1..{rules['max_depth']}")
            if not isinstance(entry, dict) or set(entry) != {"files"} or not isinstance(entry.get("files"), dict):
                errors.append(f"{where}: entry keys must be exactly ['files']")
                continue
            kinds = dict(rules["kinds"])
            files = entry["files"]
            if not set(files) <= set(kinds) or not set(rules["required"]) <= set(files):
                errors.append(f"{where}: file kinds {sorted(files)} must be within {sorted(kinds)} and include {list(rules['required'])}")
            for kind, file_entry in files.items():
                repo_path = _check_file_entry(f"{where}/{kind}", file_entry, errors)
                if kind in kinds and repo_path != f"{normalized_key}/{kinds[kind]}":
                    errors.append(f"{where}/{kind}: repo_path must be '{normalized_key}/{kinds[kind]}'")
                if repo_path:
                    expected[repo_path] = file_entry
        else:
            repo_path = _check_file_entry(where, entry, errors)
            if repo_path and not repo_path.endswith(tuple(rules["suffixes"])):
                errors.append(f"{where}: repo_path must end with {rules['suffixes']}")
            previous = expected.get(repo_path)
            if previous is not None and (
                previous.get("sha256") != entry.get("sha256") or previous.get("size_bytes") != entry.get("size_bytes")
            ):
                errors.append(f"{where}: shares '{repo_path}' with a different hash or size")
            if repo_path:
                expected[repo_path] = entry
    return expected


def check_zip_dataset(dataset: str, manifest: object, zip_path: Path) -> list[str]:
    rules = ZIP_DATASETS[dataset]
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return [f"{dataset}: manifest must be an object"]
    _check_header(dataset, manifest, rules, errors)
    expected = _expected_files(dataset, manifest, rules, errors)
    raw_zip = zip_path.read_bytes()
    if _sha256(raw_zip) != str(manifest.get("sha256", "")).strip().lower() or len(raw_zip) != manifest.get("size_bytes"):
        errors.append(f"{dataset}: zip hash or size differs from the manifest")
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            normalized = name.replace("\\", "/").strip()
            if not is_safe_archive_path(normalized):
                errors.append(f"{dataset}: zip entry '{name}' is unsafe or a directory")
                continue
            entry = expected.get(normalized)
            if entry is None:
                errors.append(f"{dataset}: zip entry '{normalized}' is not listed in the manifest")
                continue
            data = archive.read(name)
            if not data:
                errors.append(f"{dataset}: zip entry '{normalized}' is empty")
            if _sha256(data) != str(entry.get("sha256", "")).strip().lower() or len(data) != entry.get("size_bytes"):
                errors.append(f"{dataset}: zip entry '{normalized}' differs from its manifest hash or size")
            seen.add(normalized)
    for missing in sorted(set(expected) - seen):
        errors.append(f"{dataset}: '{missing}' is in the manifest but not in the zip")
    return errors


def check_file_manifest(dataset: str, manifest: object) -> list[str]:
    rules = FILE_MANIFESTS[dataset]
    if not isinstance(manifest, dict):
        return [f"{dataset}: manifest must be an object"]
    errors: list[str] = []
    if set(manifest) != FILE_MANIFEST_KEYS:
        errors.append(f"{dataset}: top-level keys {sorted(manifest)} are not exactly {sorted(FILE_MANIFEST_KEYS)}")
    if manifest.get("schema_version") != 1 or isinstance(manifest.get("schema_version"), bool):
        errors.append(f"{dataset}: schema_version must be 1")
    if manifest.get("repo") != REPO_NAME:
        errors.append(f"{dataset}: repo must be exactly {REPO_NAME}")
    airports = manifest.get("airports")
    if not isinstance(airports, dict):
        return errors + [f"{dataset}: airports must be an object"]
    seen: set[str] = set()
    for key, entry in airports.items():
        where = f"{dataset}: '{key}'"
        icao = str(key).strip().upper()
        if not icao or icao in seen:
            errors.append(f"{where}: empty or duplicate airport")
        seen.add(icao)
        repo_path = _check_file_entry(where, entry, errors)
        if repo_path and not repo_path.endswith(str(rules["suffix"])):
            errors.append(f"{where}: repo_path must end with {rules['suffix']}")
        if rules["exact_keys"] and isinstance(entry, dict):
            if not rules["icao"].fullmatch(icao):
                errors.append(f"{where}: airport key fails the visual ICAO rule")
            if repo_path.split("/")[-2:-1] != [icao] and repo_path.split("/")[-2:-1] != [str(key)]:
                errors.append(f"{where}: repo_path parent folder must be the airport")
            if not SHA_RE.fullmatch(str(entry.get("sha256", "")).strip().lower()):
                errors.append(f"{where}: sha256 must be 64 hex characters")
            size = entry.get("size_bytes")
            if not _is_int(size) or not 1 <= int(size) <= int(rules["max_bytes"]):
                errors.append(f"{where}: size_bytes must be 1..{rules['max_bytes']}")
    return errors


def _strings(value: object, where: str):
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{where}[{index}]")


def check_default_routes_references(manifests: dict[str, object]) -> list[str]:
    """Gated route overlays live only in the full feed (tools/routes_full_feed.py).

    A default manifest or the release manifest naming ``ROUTES/full/`` or a
    ``routes...-full`` asset would hand STAR-less rows to builds that cannot fly them.
    """
    errors: list[str] = []
    for name, manifest in manifests.items():
        for where, text in _strings(manifest, str(name)):
            if FULL_ROUTES_PATH in text or FULL_ROUTES_ASSET_RE.search(text):
                errors.append(f"{where}: default feed names a gated route overlay or full routes asset ('{text}')")
    return errors


def check_repo_manifests(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for dataset in FILE_MANIFESTS:
        path = root / ".voiceatc" / f"{dataset}_manifest.json"
        if path.is_file():
            errors.extend(check_file_manifest(dataset, json.loads(path.read_text(encoding="utf-8"))))
    default_routes_files = {
        name: root / relative for name, relative in DEFAULT_ROUTES_FILES.items() if (root / relative).is_file()
    }
    errors.extend(
        check_default_routes_references(
            {name: json.loads(path.read_text(encoding="utf-8")) for name, path in default_routes_files.items()}
        )
    )
    return errors


def check_release_summary(summary_path: Path) -> list[str]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for dataset, rules in ZIP_DATASETS.items():
        zip_path = Path(summary["assets"][str(rules["asset_key"])]["path"])
        errors.extend(check_zip_dataset(dataset, summary["manifests"][dataset], zip_path))
    default_manifests = dict(summary["manifests"])
    release_asset = summary["assets"].get("release_manifest", {})
    release_asset_path = Path(str(release_asset.get("path", ""))) if isinstance(release_asset, dict) else None
    if release_asset_path is not None and release_asset_path.is_file():
        default_manifests["release_manifest_asset"] = json.loads(release_asset_path.read_text(encoding="utf-8"))
    errors.extend(check_default_routes_references(default_manifests))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check default community outputs against the oldest live build's rules.")
    parser.add_argument("--summary", help="summary.json from community_release_manifest.py (checks the zips)")
    args = parser.parse_args()
    errors = check_repo_manifests(ROOT)
    if args.summary:
        errors.extend(check_release_summary(Path(args.summary)))
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(f"Stable contract guard: {len(errors)} problem(s); the default feed would break live builds.", file=sys.stderr)
        return 1
    checked = "committed per-file manifests" + (" and the release zips" if args.summary else "")
    print(f"Stable contract guard passed ({checked}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
