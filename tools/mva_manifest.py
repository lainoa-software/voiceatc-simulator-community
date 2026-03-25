#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".voiceatc" / "mva_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
BRANCH_NAME = "main"
SCHEMA_VERSION = 1
MVA_FILENAME = "mva.json"


def mva_files(root: Path = ROOT) -> list[Path]:
    return sorted(
        path for path in root.rglob(MVA_FILENAME)
        if ".git" not in path.parts and ".voiceatc" not in path.parts
    )

def ensure_text_field(value: object, label: str, path: Path) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: '{label}' must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{path}: '{label}' must not be empty")
    return text


def ensure_point(value: object, label: str, path: Path) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{path}: '{label}' must be a [lat, lon] array")
    lat = value[0]
    lon = value[1]
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise ValueError(f"{path}: '{label}' entries must be numeric")
    return [float(lat), float(lon)]


def _normalize_airports(value: object, label: str, path: Path) -> list[str]:
    tokens = [value] if isinstance(value, str) else value
    if not isinstance(tokens, list):
        raise ValueError(f"{path}: '{label}' must be a string or array")

    airports: list[str] = []
    for token in tokens:
        airport = ensure_text_field(token, label, path).upper()
        if airport not in airports:
            airports.append(airport)
    if not airports:
        raise ValueError(f"{path}: '{label}' must list at least one airport")
    return airports


def validate_mva_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"{path}: mva file must be a JSON object")

    airports = _normalize_airports(payload.get("airport", payload.get("airports")), "airport", path)

    areas = payload.get("mva_areas")
    if not isinstance(areas, list) or not areas:
        raise ValueError(f"{path}: missing non-empty mva_areas array")

    seen_area_ids: set[str] = set()
    for index, area in enumerate(areas):
        if not isinstance(area, dict):
            raise ValueError(f"{path}: area row {index} must be an object")

        area_id = ensure_text_field(area.get("area_id"), "area_id", path)
        if area_id in seen_area_ids:
            raise ValueError(f"{path}: duplicate area_id '{area_id}'")
        seen_area_ids.add(area_id)

        minimum_altitude_ft = area.get("minimum_altitude_ft")
        if not isinstance(minimum_altitude_ft, int) or minimum_altitude_ft <= 0:
            raise ValueError(f"{path}: area '{area_id}' must have positive integer minimum_altitude_ft")

        polygon = area.get("polygon")
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise ValueError(f"{path}: area '{area_id}' polygon must contain at least 3 points")
        for point_index, point in enumerate(polygon):
            ensure_point(point, f"polygon[{point_index}]", path)

        labels = area.get("labels", [])
        if labels is None:
            labels = []
        if not isinstance(labels, list):
            raise ValueError(f"{path}: area '{area_id}' labels must be an array")
        for label_index, label in enumerate(labels):
            if not isinstance(label, dict):
                raise ValueError(f"{path}: area '{area_id}' label {label_index} must be an object")
            ensure_text_field(label.get("text"), "text", path)
            ensure_point(label.get("position"), "position", path)

    return {
        "airport": airports[0],
        "airports": airports,
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
    for path in mva_files(root):
        entry = validate_mva_file(path, root)
        for airport in entry["airports"]:
            if airport in airports:
                raise ValueError(f"duplicate airport '{airport}' across mva files")
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
    parser = argparse.ArgumentParser(description="Validate mva.json files and generate the community MVA manifest.")
    parser.add_argument("--write", action="store_true", help="Write .voiceatc/mva_manifest.json")
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
        print(f"Validated {len(manifest['airports'])} MVA files.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
