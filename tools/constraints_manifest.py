#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".voiceatc" / "constraints_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
SCHEMA_VERSION = 1
CONSTRAINTS_FILENAME = "constraints.json"
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


def constraints_files(root: Path = ROOT) -> list[Path]:
    return sorted(
        path
        for path in root.rglob(CONSTRAINTS_FILENAME)
        if not any(part in IGNORED_PARTS for part in path.parts)
    )


def ensure_text_field(value: object, label: str, path: Path) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: '{label}' must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{path}: '{label}' must not be empty")
    return text


def validate_constraints_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{path}: constraints file must be a JSON object")

    airport = ensure_text_field(payload.get("airport"), "airport", path).upper()
    parent_folder = path.parent.name.strip().upper()
    if airport != parent_folder:
        raise ValueError(f"{path}: airport '{airport}' must match parent folder '{parent_folder}'")

    repo_path = path.relative_to(root).as_posix()
    return {
        "airport": airport,
        "repo_path": repo_path,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def build_manifest(
    root: Path = ROOT,
    published_at: str | None = None,
) -> dict[str, object]:
    airports: dict[str, dict[str, object]] = {}
    for path in constraints_files(root):
        entry = validate_constraints_file(path, root)
        airport = str(entry["airport"])
        if airport in airports:
            raise ValueError(f"duplicate airport '{airport}' across constraints files")
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

        generated_entry = validate_constraints_file(candidate, root)
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
    parser = argparse.ArgumentParser(description="Validate constraints.json files and generate the community constraints manifest.")
    parser.add_argument("--write", action="store_true", help="Write .voiceatc/constraints_manifest.json")
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
        print(f"Validated {len(manifest['airports'])} constraints files and {validated_entries} manifest entries.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
