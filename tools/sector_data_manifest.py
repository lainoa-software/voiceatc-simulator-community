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
MANIFEST_PATH = ROOT / ".voiceatc" / "sector_data_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
BRANCH_NAME = "main"
SCHEMA_VERSION = 1
SECTOR_FILE_NAMES = {
    "configs": "sector_configs.json",
    "definitions": "sector_definitions.json",
    "influence": "sector_influence.json",
}
FILE_KIND_BY_NAME = {file_name: kind for kind, file_name in SECTOR_FILE_NAMES.items()}
FILE_KIND_ORDER = ("configs", "definitions", "influence")


def _tracked_sector_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for file_name in SECTOR_FILE_NAMES.values():
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


def ensure_text_field(value: object, label: str, path: Path) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: '{label}' must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{path}: '{label}' must not be empty")
    return text


def ensure_point(value: object, label: str, path: Path) -> list[float]:
    if isinstance(value, list) and len(value) >= 2:
        lat = value[0]
        lon = value[1]
    elif isinstance(value, dict):
        lat = value.get("lat")
        lon = value.get("lon")
    else:
        raise ValueError(f"{path}: '{label}' must be a [lat, lon] array or object with lat/lon")
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
        raise ValueError(f"{path}: sector data file must be a JSON object")
    return payload, raw_bytes


def _coerce_array(value: object, label: str, path: Path) -> list[object]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        return [value]
    raise ValueError(f"{path}: '{label}' must be a string, object, or array")


def _normalize_string_tokens(value: object, label: str, path: Path) -> list[str]:
    if isinstance(value, list):
        tokens = value
    elif isinstance(value, str):
        normalized = (
            value.replace(";", ",")
            .replace("|", ",")
            .replace("+", ",")
            .replace("\t", ",")
            .replace(" ", ",")
        )
        tokens = normalized.split(",")
    else:
        raise ValueError(f"{path}: '{label}' must be a string or array")

    normalized_tokens: list[str] = []
    for token in tokens:
        if not isinstance(token, str):
            raise ValueError(f"{path}: '{label}' entries must be strings")
        text = token.strip()
        if text:
            normalized_tokens.append(text)
    return normalized_tokens


def validate_sector_configs_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    configs = payload.get("sector_configs", payload.get("sector_configurations", payload.get("configs")))
    if not isinstance(configs, list) or not configs:
        raise ValueError(f"{path}: missing non-empty sector_configs array")

    seen_ids: set[str] = set()
    for index, row in enumerate(configs):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: sector config row {index} must be an object")

        config_id = ensure_text_field(
            row.get("sector_config_id", row.get("config_id", row.get("id", row.get("SECTOR_CONFIG_ID", "")))),
            "sector_config_id",
            path,
        ).upper()
        if config_id in seen_ids:
            raise ValueError(f"{path}: duplicate sector_config_id '{config_id}'")
        seen_ids.add(config_id)

        if "runway_configs" in row or "runway_configurations" in row or "runways" in row:
            runway_configs = row.get("runway_configs", row.get("runway_configurations", row.get("runways", [])))
            runway_tokens = _normalize_string_tokens(runway_configs, "runway_configs", path)
            if not runway_tokens:
                raise ValueError(f"{path}: sector_config '{config_id}' runway_configs must not be empty when present")

        sectors = _coerce_array(
            row.get("sectors", row.get("sector_entries", row.get("sector_ids", row.get("sector_id", [])))),
            "sectors",
            path,
        )
        if not sectors:
            raise ValueError(f"{path}: sector_config '{config_id}' must define at least one sector")
        for sector_index, sector in enumerate(sectors):
            if isinstance(sector, dict):
                sector_id_raw = sector.get("sector_ids", sector.get("sector_id", sector.get("sector", sector.get("id", sector.get("SECTOR_ID", "")))))
                if isinstance(sector_id_raw, list):
                    for item in sector_id_raw:
                        if not isinstance(item, str):
                            raise ValueError(f"{path}: sector_config '{config_id}' sector {sector_index} sector_id entries must be strings")
                else:
                    ensure_text_field(sector_id_raw, "sector_id", path)
                frequency = sector.get("frequency", None)
                if frequency is not None and not isinstance(frequency, str):
                    raise ValueError(f"{path}: sector_config '{config_id}' frequency must be a string")
            elif isinstance(sector, str):
                if not sector.strip():
                    raise ValueError(f"{path}: sector_config '{config_id}' sector {sector_index} must not be empty")
            else:
                raise ValueError(f"{path}: sector_config '{config_id}' sector {sector_index} must be a string or object")

    return {
        "repo_path": safe_repo_path(path, root),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def validate_sector_definitions_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    definitions = payload.get("sector_definitions", payload.get("definitions", payload.get("sectors")))
    if not isinstance(definitions, list) or not definitions:
        raise ValueError(f"{path}: missing non-empty sector_definitions array")

    for index, row in enumerate(definitions):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: sector definition row {index} must be an object")

        sector_id = ensure_text_field(
            row.get("sector_id", row.get("sector", row.get("id", row.get("SECTOR_ID", "")))),
            "sector_id",
            path,
        )

        lower_limit = row.get("lower_limit", row.get("floor", None))
        higher_limit = row.get("higher_limit", row.get("ceiling", None))
        if lower_limit is not None and not isinstance(lower_limit, (int, float)):
            raise ValueError(f"{path}: sector '{sector_id}' lower_limit must be numeric")
        if higher_limit is not None and not isinstance(higher_limit, (int, float)):
            raise ValueError(f"{path}: sector '{sector_id}' higher_limit must be numeric")
        if lower_limit is not None and higher_limit is not None and float(higher_limit) <= float(lower_limit):
            raise ValueError(f"{path}: sector '{sector_id}' higher_limit must be greater than lower_limit")

        polygon = row.get("polygon", row.get("points", row.get("coordinates", [])))
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise ValueError(f"{path}: sector '{sector_id}' polygon must contain at least 3 points")
        for point_index, point in enumerate(polygon):
            ensure_point(point, f"polygon[{point_index}]", path)

    return {
        "repo_path": safe_repo_path(path, root),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def validate_sector_influence_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    influences = payload.get("sector_influence", payload.get("sector_influences", payload.get("sectors")))
    if not isinstance(influences, list) or not influences:
        raise ValueError(f"{path}: missing non-empty sector_influence array")

    for index, row in enumerate(influences):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: sector influence row {index} must be an object")

        sector_id = ensure_text_field(
            row.get("sector_id", row.get("sector", row.get("id", row.get("SECTOR_ID", "")))),
            "sector_id",
            path,
        )
        airports = _normalize_string_tokens(
            row.get("airports", row.get("sector_airports", row.get("influenced_airports", row.get("AIRPORTS", [])))),
            "airports",
            path,
        )
        if not airports:
            raise ValueError(f"{path}: sector '{sector_id}' must list at least one influenced airport")

    return {
        "repo_path": safe_repo_path(path, root),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def validate_sector_bundle(bundle_dir: Path, bundle_files: dict[str, Path], root: Path = ROOT) -> dict[str, object]:
    bundle_repo_path = safe_repo_path(bundle_dir, root)
    missing_kinds = [kind for kind in FILE_KIND_ORDER if kind not in bundle_files]
    if missing_kinds:
        raise ValueError(f"{bundle_repo_path}: missing sector bundle files: {', '.join(missing_kinds)}")

    files = {
        "configs": validate_sector_configs_file(bundle_files["configs"], root),
        "definitions": validate_sector_definitions_file(bundle_files["definitions"], root),
        "influence": validate_sector_influence_file(bundle_files["influence"], root),
    }
    return {
        "bundle_path": bundle_repo_path,
        "files": files,
    }


def current_commit_sha(root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()


def build_manifest(root: Path = ROOT, commit_sha: str | None = None) -> dict[str, object]:
    bundle_candidates: dict[Path, dict[str, Path]] = {}
    for path in _tracked_sector_files(root):
        kind = FILE_KIND_BY_NAME.get(path.name)
        if kind is None:
            continue
        bundle_candidates.setdefault(path.parent, {})[kind] = path

    bundles: dict[str, dict[str, object]] = {}
    for bundle_dir in sorted(bundle_candidates):
        validated_bundle = validate_sector_bundle(bundle_dir, bundle_candidates[bundle_dir], root)
        bundle_path = str(validated_bundle["bundle_path"])
        if bundle_path in bundles:
            raise ValueError(f"duplicate sector bundle '{bundle_path}'")
        bundles[bundle_path] = {"files": validated_bundle["files"]}

    return {
        "schema_version": SCHEMA_VERSION,
        "repo": REPO_NAME,
        "branch": BRANCH_NAME,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_sha": commit_sha if commit_sha is not None else current_commit_sha(root),
        "bundles": dict(sorted(bundles.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate sector JSON bundles and generate the community sector-data manifest.")
    parser.add_argument("--write", action="store_true", help="Write .voiceatc/sector_data_manifest.json")
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
        print(f"Validated {len(manifest['bundles'])} sector data bundles.")
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
