#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".voiceatc" / "runway_configs_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
BRANCH_NAME = "main"
SCHEMA_VERSION = 1
RUNWAY_CONFIG_FILENAME = "runway_configs.json"
LEGACY_RUNWAY_CONFIG_FILENAME = "runway_config.json"

# Zero-padded, as Navigraph publishes them. The game compares configuration
# runways against the airport's Navigraph identifiers without padding either
# side, so an unpadded '8L' silently matches nothing and the whole
# configuration resolves to no runways. US sources publish identifiers
# unpadded, which is how PHNL shipped four of them.
RUNWAY_IDENT_RE = re.compile(r"^(0[1-9]|[12][0-9]|3[0-6])[LCR]?$")

# The separators the game accepts. ConfigOptions._parse_runway_config_field
# rewrites ',', ';', '|', '+', '\', tab and space to '/' and then splits on '/',
# so '/' is the game's canonical separator and has to be listed here too. Leaving
# it out rejected '22L/22R' — the way charts write a runway pair — with a
# zero-padding error that named the whole field as one identifier.
RUNWAY_FIELD_SEPARATORS = re.compile(r"[,;|+\\/\t ]+")


def _tracked_runway_files(root: Path, filename: str) -> list[Path]:
    return sorted(
        path for path in root.rglob(filename)
        if ".git" not in path.parts and ".voiceatc" not in path.parts
    )


def legacy_runway_files(root: Path = ROOT) -> list[Path]:
    return _tracked_runway_files(root, LEGACY_RUNWAY_CONFIG_FILENAME)


def runway_files(root: Path = ROOT) -> list[Path]:
    legacy_files = legacy_runway_files(root)
    if legacy_files:
        listed = ", ".join(path.relative_to(root).as_posix() for path in legacy_files[:5])
        remaining = len(legacy_files) - 5
        if remaining > 0:
            listed += f", +{remaining} more"
        raise ValueError(
            f"legacy runway filename '{LEGACY_RUNWAY_CONFIG_FILENAME}' is not allowed; "
            f"use '{RUNWAY_CONFIG_FILENAME}': {listed}"
        )
    return _tracked_runway_files(root, RUNWAY_CONFIG_FILENAME)


def ensure_text_field(value: object, label: str, path: Path) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: '{label}' must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{path}: '{label}' must not be empty")
    return text


def runway_idents(value: str | list[object]) -> list[str]:
    """Split an 'arr'/'dep' field the way the game does, dropping blanks."""
    if isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        parts = RUNWAY_FIELD_SEPARATORS.split(value.strip())
    return [part for part in parts if part]


def validate_runway_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{path}: runway config must be a JSON object")

    airport = ensure_text_field(payload.get("airport"), "airport", path).upper()
    parent_folder = path.parent.name.strip().upper()
    if airport != parent_folder:
        raise ValueError(f"{path}: airport '{airport}' must match parent folder '{parent_folder}'")

    configs = payload.get("runway_configurations", payload.get("runway_configs"))
    if not isinstance(configs, list) or not configs:
        raise ValueError(f"{path}: missing non-empty runway_configurations/runway_configs array")

    seen_ids: set[str] = set()
    for index, row in enumerate(configs):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: config row {index} must be an object")

        config_id = ensure_text_field(row.get("id"), "id", path).upper()
        if config_id in seen_ids:
            raise ValueError(f"{path}: duplicate config id '{config_id}'")
        seen_ids.add(config_id)

        if "name" in row and not isinstance(row["name"], str):
            raise ValueError(f"{path}: config '{config_id}' field 'name' must be a string")

        for key in ("arr", "dep"):
            value = row.get(key)
            if not isinstance(value, (str, list)):
                raise ValueError(f"{path}: config '{config_id}' field '{key}' must be a string or array")
            for ident in runway_idents(value):
                if not RUNWAY_IDENT_RE.match(ident):
                    raise ValueError(
                        f"{path}: config '{config_id}' field '{key}' runway '{ident}' must be a "
                        f"zero-padded identifier such as '08L'"
                    )

    return {
        "airport": airport,
        "repo_path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def current_commit_sha(root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()


def build_manifest(root: Path = ROOT, commit_sha: str | None = None) -> dict[str, object]:
    airports: dict[str, dict[str, object]] = {}
    for path in runway_files(root):
        entry = validate_runway_file(path, root)
        airport = str(entry["airport"])
        if airport in airports:
            raise ValueError(f"duplicate airport '{airport}' across runway config files")
        airports[airport] = {
            "repo_path": entry["repo_path"],
            "sha256": entry["sha256"],
            "size_bytes": entry["size_bytes"],
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "repo": REPO_NAME,
        "branch": BRANCH_NAME,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_sha": commit_sha if commit_sha is not None else current_commit_sha(root),
        "airports": dict(sorted(airports.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate runway_configs.json files and generate the community runway-configs manifest.")
    parser.add_argument("--write", action="store_true", help="Write .voiceatc/runway_configs_manifest.json")
    parser.add_argument("--validate-only", action="store_true", help="Validate only, without writing the manifest")
    args = parser.parse_args()

    try:
        manifest = build_manifest()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.write:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    elif args.validate_only:
        print(f"Validated {len(manifest['airports'])} runway config files.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
