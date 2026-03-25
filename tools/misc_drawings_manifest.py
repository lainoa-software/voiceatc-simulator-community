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
MANIFEST_PATH = ROOT / ".voiceatc" / "misc_drawings_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
BRANCH_NAME = "main"
SCHEMA_VERSION = 1
MISC_DRAWINGS_FILENAME = "misc_drawings.json"


def misc_drawings_files(root: Path = ROOT) -> list[Path]:
    return sorted(
        path
        for path in root.rglob(MISC_DRAWINGS_FILENAME)
        if ".git" not in path.parts and ".voiceatc" not in path.parts
    )


def ensure_text_field(value: object, label: str, path: Path) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: '{label}' must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{path}: '{label}' must not be empty")
    return text


def safe_repo_path(path: Path, root: Path = ROOT) -> str:
    repo_path = path.relative_to(root).as_posix()
    if not repo_path or repo_path.startswith("/") or repo_path.startswith("../") or "/../" in repo_path:
        raise ValueError(f"unsafe repo path '{repo_path}'")
    return repo_path


def ensure_point(value: object, label: str, path: Path) -> list[float]:
    if isinstance(value, list) and len(value) >= 2:
        lat = value[0]
        lon = value[1]
    elif isinstance(value, dict):
        if "point" in value:
            return ensure_point(value["point"], label, path)
        if "latlon" in value:
            return ensure_point(value["latlon"], label, path)
        lat = value.get("lat")
        lon = value.get("lon")
    else:
        raise ValueError(f"{path}: '{label}' must be a [lat, lon] array or object with point/latlon/lat+lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise ValueError(f"{path}: '{label}' entries must be numeric")
    return [float(lat), float(lon)]


def _load_json_object(path: Path) -> tuple[dict[str, object], bytes]:
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: misc drawings file must be a JSON object")
    return payload, raw_bytes


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


def _parse_airports_metadata(payload: dict[str, object], path: Path) -> list[str]:
    if "airports" in payload:
        return _normalize_airports(payload.get("airports"), "airports", path)
    if "airport" in payload:
        return _normalize_airports(payload.get("airport"), "airport", path)
    raise ValueError(f"{path}: missing 'airport' or 'airports' metadata")


def _validate_line_sections(value: object, dataset_label: str, path: Path) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{path}: '{dataset_label}.line_sections' must be an array")
    for section_index, section in enumerate(value):
        if not isinstance(section, dict):
            raise ValueError(f"{path}: '{dataset_label}.line_sections[{section_index}]' must be an object")
        points = section.get("points", [])
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError(f"{path}: '{dataset_label}.line_sections[{section_index}].points' must contain at least 2 points")
        for point_index, point in enumerate(points):
            ensure_point(point, f"{dataset_label}.line_sections[{section_index}].points[{point_index}]", path)
        if "color" in section and not isinstance(section["color"], str):
            raise ValueError(f"{path}: '{dataset_label}.line_sections[{section_index}].color' must be a string")
        for key in ("dash_length", "gap_length"):
            if key in section and not isinstance(section[key], (int, float)):
                raise ValueError(f"{path}: '{dataset_label}.line_sections[{section_index}].{key}' must be numeric")


def _validate_filled_polygons(value: object, dataset_label: str, path: Path) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{path}: '{dataset_label}.filled_polygons' must be an array")
    for polygon_index, polygon in enumerate(value):
        if not isinstance(polygon, dict):
            raise ValueError(f"{path}: '{dataset_label}.filled_polygons[{polygon_index}]' must be an object")
        points = polygon.get("points", [])
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError(f"{path}: '{dataset_label}.filled_polygons[{polygon_index}].points' must contain at least 3 points")
        for point_index, point in enumerate(points):
            ensure_point(point, f"{dataset_label}.filled_polygons[{polygon_index}].points[{point_index}]", path)
        if "color" in polygon and not isinstance(polygon["color"], str):
            raise ValueError(f"{path}: '{dataset_label}.filled_polygons[{polygon_index}].color' must be a string")


def _validate_labels(value: object, dataset_label: str, path: Path) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{path}: '{dataset_label}.labels' must be an array")
    for label_index, label in enumerate(value):
        if not isinstance(label, dict):
            raise ValueError(f"{path}: '{dataset_label}.labels[{label_index}]' must be an object")
        ensure_text_field(label.get("text", label.get("label", "")), "text", path)
        ensure_point(label, f"{dataset_label}.labels[{label_index}]", path)
        if "color" in label and not isinstance(label["color"], str):
            raise ValueError(f"{path}: '{dataset_label}.labels[{label_index}].color' must be a string")


def _validate_dataset(dataset: object, dataset_label: str, path: Path) -> None:
    if not isinstance(dataset, dict):
        raise ValueError(f"{path}: '{dataset_label}' must be an object")
    if "runway_config" in dataset:
        runway_config = dataset["runway_config"]
        if isinstance(runway_config, list):
            for item in runway_config:
                if not isinstance(item, str):
                    raise ValueError(f"{path}: '{dataset_label}.runway_config' entries must be strings")
        elif not isinstance(runway_config, str):
            raise ValueError(f"{path}: '{dataset_label}.runway_config' must be a string or array")

    has_supported_section = False
    if "line_sections" in dataset:
        has_supported_section = True
        _validate_line_sections(dataset["line_sections"], dataset_label, path)
    if "filled_polygons" in dataset:
        has_supported_section = True
        _validate_filled_polygons(dataset["filled_polygons"], dataset_label, path)
    if "labels" in dataset:
        has_supported_section = True
        _validate_labels(dataset["labels"], dataset_label, path)

    if not has_supported_section:
        raise ValueError(f"{path}: '{dataset_label}' must contain line_sections, filled_polygons, or labels")


def validate_misc_drawings_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    airports = _parse_airports_metadata(payload, path)

    drawings = payload.get("drawings", None)
    if drawings is not None:
        if not isinstance(drawings, list) or not drawings:
            raise ValueError(f"{path}: 'drawings' must be a non-empty array when present")
        for index, drawing in enumerate(drawings):
            _validate_dataset(drawing, f"drawings[{index}]", path)
    else:
        _validate_dataset(payload, "misc_drawings", path)

    return {
        "airports": airports,
        "repo_path": safe_repo_path(path, root),
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
    for path in misc_drawings_files(root):
        entry = validate_misc_drawings_file(path, root)
        for airport in entry["airports"]:
            if airport in airports:
                raise ValueError(f"duplicate airport '{airport}' across misc drawings files")
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
    parser = argparse.ArgumentParser(description="Validate misc_drawings.json files and generate the community misc-drawings manifest.")
    parser.add_argument("--write", action="store_true", help="Write .voiceatc/misc_drawings_manifest.json")
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
        print(f"Validated {len(manifest['airports'])} misc drawings file mappings.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
