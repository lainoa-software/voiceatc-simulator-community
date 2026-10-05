#!/usr/bin/env python3
from __future__ import annotations

try:
    from . import airac_overrides
except ImportError:
    import airac_overrides

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from legacy_contract import LEGACY_CONSTRAINTS_MANIFEST_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".voiceatc" / "constraints_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
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
VALIDATION_REPAIR_HINT = (
    "This manifest is CI-owned: format-all-json.yml refreshes it after every merge and "
    "daily-release.yml rebuilds it nightly, both with --write. A failure here means the "
    "writer and the checker disagree, which is a tooling bug rather than a contribution "
    "problem. Contributions are gated on --validate-sources, which ignores this manifest."
)


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
    airac_overrides.validate_references(payload, path)
    result = {}
    for tier, document in airac_overrides.documents(payload):
        checked = _validate_constraints_document(document, path, root, raw_bytes, tier)
        if not tier:
            result = checked
    return result


def _validate_constraints_document(payload: dict, path: Path, root: Path, raw_bytes: bytes, tier: str) -> dict:

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
        "schema_version": LEGACY_CONSTRAINTS_MANIFEST_SCHEMA_VERSION,
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

    if int(payload.get("schema_version", -1)) != LEGACY_CONSTRAINTS_MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"{manifest_path}: schema_version must be {LEGACY_CONSTRAINTS_MANIFEST_SCHEMA_VERSION}")

    repo = str(payload.get("repo", "")).strip()
    if repo != REPO_NAME:
        raise ValueError(f"{manifest_path}: repo must be '{REPO_NAME}'")

    airports = payload.get("airports", {})
    if not isinstance(airports, dict):
        raise ValueError(f"{manifest_path}: airports must be an object")

    seen_airports: set[str] = set()
    for airport_key in airports:
        airport = str(airport_key).strip().upper()
        if not airport:
            raise ValueError(f"{manifest_path}: airport key must not be empty")
        if airport in seen_airports:
            raise ValueError(f"{manifest_path}: duplicate airport '{airport}' in manifest")
        seen_airports.add(airport)

    if expected_airports is None:
        generated = build_manifest(root, published_at="")
        expected_airports = set(generated["airports"])
    expected_airports = {str(airport).strip().upper() for airport in expected_airports}
    missing_airports = sorted(expected_airports - seen_airports)
    unexpected_airports = sorted(seen_airports - expected_airports)
    if missing_airports or unexpected_airports:
        differences: list[str] = []
        if missing_airports:
            differences.append(f"missing entries: {', '.join(missing_airports)}")
        if unexpected_airports:
            differences.append(f"unexpected entries: {', '.join(unexpected_airports)}")
        message = f"{manifest_path}: manifest airport set does not match source files ({'; '.join(differences)})"
        raise ValueError(message)

    for airport_key, entry in airports.items():
        airport = str(airport_key).strip().upper()
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
    parser.add_argument("--validate-only", action="store_true", help="Validate source files and the checked-in manifest (run this after --write)")
    parser.add_argument("--validate-sources", action="store_true", help="Validate source files only; the manifest is CI-owned")
    parser.add_argument("--preserve-published-at", action="store_true", help="Retain published_at while refreshing hashes after formatting")
    args = parser.parse_args()
    if args.preserve_published_at and not args.write:
        parser.error("--preserve-published-at requires --write")

    try:
        published_at = existing_published_at() if args.preserve_published_at else None
        manifest = build_manifest(published_at=published_at)
        validated_entries = 0
        if args.validate_only:
            validated_entries = validate_existing_manifest_entries(expected_airports=set(manifest["airports"]))
    except Exception as exc:
        message = str(exc)
        if args.validate_only:
            message = f"{message}\n{VALIDATION_REPAIR_HINT}"
        print(message, file=sys.stderr)
        return 1

    if args.write:
        manifest = airac_overrides.publish_raw_manifest(ROOT, MANIFEST_PATH, manifest)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"Wrote {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    elif args.validate_only:
        print(f"Validated {len(manifest['airports'])} constraints files and {validated_entries} manifest entries.")
    elif args.validate_sources:
        print(f"Validated {len(manifest['airports'])} constraints files.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
