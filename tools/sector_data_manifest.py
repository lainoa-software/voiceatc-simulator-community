#!/usr/bin/env python3
from __future__ import annotations

try:
    from . import airac_overrides
    from .content_files import content_files
except ImportError:  # run as a script, or loaded by file path (tests)
    import sys
    from pathlib import Path

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import airac_overrides
    from content_files import content_files

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
AIRSPACE_CAPABILITY = "community.airspace_files"
SECTOR_FILE_NAMES = {
    "tma_structure": "tma_structure.json",
    "tma_coordination": "tma_coordination.json",
    "definitions": "sector_definitions.json",
    "acc_structure": "acc_structure.json",
    "acc_coordination": "acc_coordination.json",
}
LEGACY_GENERATED_FILE_NAMES = ("sector_configs.json", "sector_influence.json")
FILE_KIND_BY_NAME = {file_name: kind for kind, file_name in SECTOR_FILE_NAMES.items()}
TMA_REQUIRED_KINDS = ("tma_structure", "definitions")
ACC_REQUIRED_KINDS = ("acc_structure",)


def _tracked_sector_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for file_name in SECTOR_FILE_NAMES.values():
        paths.extend(content_files(root, file_name))
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


def _require_schema2(payload: dict[str, object], path: Path) -> None:
    schema = payload.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema != 2:
        raise ValueError(f"{path}: schema must be 2")


def _file_entry(path: Path, root: Path, raw_bytes: bytes, *, requires: list[str] | None = None) -> dict[str, object]:
    entry: dict[str, object] = {
        "repo_path": safe_repo_path(path, root),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }
    if requires is not None:
        entry["requires"] = list(requires)
    return entry


def validate_tma_structure_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    airac_overrides.validate_references(payload, path)
    result: dict[str, object] = {}
    for tier, document in airac_overrides.documents(payload):
        _require_schema2(document, path)
        units = document.get("units")
        if not isinstance(units, list):
            raise ValueError(f"{path}: 'units' must be an array")
        for index, unit in enumerate(units):
            if not isinstance(unit, dict):
                raise ValueError(f"{path}: units[{index}] must be an object")
            ensure_text_field(unit.get("id"), f"units[{index}].id", path)
        layouts = document.get("layouts")
        if not isinstance(layouts, list) or not layouts:
            raise ValueError(f"{path}: missing non-empty layouts array")
        for index, layout in enumerate(layouts):
            if not isinstance(layout, dict):
                raise ValueError(f"{path}: layouts[{index}] must be an object")
            ensure_text_field(layout.get("id"), f"layouts[{index}].id", path)
            positions = layout.get("positions")
            if not isinstance(positions, list) or not positions:
                raise ValueError(f"{path}: layouts[{index}].positions must be a non-empty array")
        if not tier:
            result = _file_entry(path, root, raw_bytes, requires=[AIRSPACE_CAPABILITY])
    return result


def validate_tma_coordination_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    _require_schema2(payload, path)
    agreements = payload.get("agreements")
    if not isinstance(agreements, list):
        raise ValueError(f"{path}: 'agreements' must be an array")
    for index, row in enumerate(agreements):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: agreements[{index}] must be an object")
        ensure_text_field(row.get("name"), f"agreements[{index}].name", path)
        ensure_text_field(row.get("from"), f"agreements[{index}].from", path)
        ensure_text_field(row.get("to"), f"agreements[{index}].to", path)
    return _file_entry(path, root, raw_bytes, requires=[AIRSPACE_CAPABILITY])


def validate_acc_structure_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    _require_schema2(payload, path)
    units = payload.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError(f"{path}: missing non-empty units array")
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise ValueError(f"{path}: units[{index}] must be an object")
        ensure_text_field(unit.get("id"), f"units[{index}].id", path)
        ensure_text_field(unit.get("call_sign"), f"units[{index}].call_sign", path)
        services = unit.get("services")
        if not isinstance(services, list) or not services:
            raise ValueError(f"{path}: units[{index}].services must be a non-empty array")
        frequencies = unit.get("frequencies")
        if not isinstance(frequencies, list) or not frequencies:
            raise ValueError(f"{path}: units[{index}].frequencies must be a non-empty array")
    if "layouts" in payload and not isinstance(payload["layouts"], list):
        raise ValueError(f"{path}: 'layouts' must be an array")
    return _file_entry(path, root, raw_bytes, requires=[AIRSPACE_CAPABILITY])


def validate_acc_coordination_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    return validate_tma_coordination_file(path, root)


def validate_sector_definitions_file(path: Path, root: Path = ROOT) -> dict[str, object]:
    payload, raw_bytes = _load_json_object(path)
    airac_overrides.validate_references(payload, path)
    result: dict[str, object] = {}
    for tier, document in airac_overrides.documents(payload):
        checked = _validate_sector_definitions_document(document, path, root, raw_bytes, tier)
        if not tier:
            result = checked
    return result


def _definition_sector_ids(row: dict[str, object], path: Path) -> list[str]:
    if "sector_ids" in row:
        raw_ids = row["sector_ids"]
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValueError(f"{path}: 'sector_ids' must be a non-empty array")
        return [ensure_text_field(item, "sector_ids[]", path).upper() for item in raw_ids]
    return [
        ensure_text_field(
            row.get("sector_id", row.get("sector", row.get("id", row.get("SECTOR_ID", "")))),
            "sector_id",
            path,
        ).upper()
    ]


def _validate_sector_definitions_document(payload: dict, path: Path, root: Path, raw_bytes: bytes, tier: str) -> dict:
    definitions = payload.get("sector_definitions", payload.get("definitions", payload.get("sectors")))
    if not isinstance(definitions, list) or not definitions:
        raise ValueError(f"{path}: missing non-empty sector_definitions array")

    for index, row in enumerate(definitions):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: sector definition row {index} must be an object")

        sector_id = _definition_sector_ids(row, path)[0]

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
        points = [ensure_point(point, f"polygon[{point_index}]", path) for point_index, point in enumerate(polygon)]
        defect = polygon_ring_defect(points)
        if defect:
            raise ValueError(f"{path}: sector '{sector_id}' definition {index} polygon {defect}")

    return _file_entry(path, root, raw_bytes)


def _cross(origin: list[float], a: list[float], b: list[float]) -> float:
    return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])


def _on_segment(a: list[float], b: list[float], point: list[float]) -> bool:
    return min(a[0], b[0]) <= point[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])


def _segments_meet(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    """True when segment ab and segment cd share any point, a touch or a collinear overlap included."""
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    if ((d1 > 0) != (d2 > 0) and d1 != 0 and d2 != 0) and ((d3 > 0) != (d4 > 0) and d3 != 0 and d4 != 0):
        return True
    return (
        (d1 == 0 and _on_segment(c, d, a))
        or (d2 == 0 and _on_segment(c, d, b))
        or (d3 == 0 and _on_segment(a, b, c))
        or (d4 == 0 and _on_segment(a, b, d))
    )


def polygon_ring_defect(points: list[list[float]]) -> str | None:
    """Why a sector piece's outline is not a simple ring, or None when it is one."""
    ring = points[:-1] if len(points) > 1 and points[0] == points[-1] else points
    count = len(ring)
    seen: dict[tuple[float, float], int] = {}
    for index, point in enumerate(ring):
        key = (point[0], point[1])
        if key in seen:
            kind = "repeats the point of its neighbour" if index - seen[key] == 1 else "revisits a point"
            return f"{kind} [{point[0]}, {point[1]}] (points {seen[key]} and {index}); a piece must be a simple ring"
        seen[key] = index
    edges = sorted(range(count), key=lambda i: min(ring[i][0], ring[(i + 1) % count][0]))
    for position, i in enumerate(edges):
        a, b = ring[i], ring[(i + 1) % count]
        for j in edges[position + 1:]:
            c, d = ring[j], ring[(j + 1) % count]
            if min(c[0], d[0]) > max(a[0], b[0]):
                break
            if (j - i) % count in (1, count - 1):
                forward = (i + 1) % count == j
                shared, near, far = (b, a, d) if forward else (a, b, c)
                dot = (near[0] - shared[0]) * (far[0] - shared[0]) + (near[1] - shared[1]) * (far[1] - shared[1])
                if _cross(shared, near, far) == 0 and dot > 0:
                    return f"folds back on itself at [{shared[0]}, {shared[1]}]; a piece must be a simple ring"
            elif _segments_meet(a, b, c, d):
                return f"crosses itself between edges {i} and {j}; a piece must be a simple ring"
    return None


def _referenced_tma_sectors(tma_structure: dict) -> set[str]:
    referenced: set[str] = set()
    for layout in tma_structure.get("layouts", []):
        if not isinstance(layout, dict):
            continue
        for pos in layout.get("positions", []):
            if isinstance(pos, dict) and pos.get("sector"):
                referenced.add(str(pos["sector"]).strip().upper())
        for duty in layout.get("on_duty", []):
            if isinstance(duty, dict):
                for sid in duty.get("sectors", []):
                    if sid:
                        referenced.add(str(sid).strip().upper())
    return referenced


def validate_sector_bundle(bundle_dir: Path, bundle_files: dict[str, Path], root: Path = ROOT) -> dict[str, object]:
    bundle_repo_path = safe_repo_path(bundle_dir, root)
    is_acc = "acc_structure" in bundle_files or "acc_coordination" in bundle_files
    is_tma = "tma_structure" in bundle_files or "tma_coordination" in bundle_files
    if is_acc and is_tma:
        raise ValueError(f"{bundle_repo_path}: cannot mix ACC and TMA files in one bundle")

    files: dict[str, object] = {}
    if is_acc:
        missing_kinds = [kind for kind in ACC_REQUIRED_KINDS if kind not in bundle_files]
        if missing_kinds:
            raise ValueError(f"{bundle_repo_path}: missing ACC bundle files: {', '.join(missing_kinds)}")
        files["acc_structure"] = validate_acc_structure_file(bundle_files["acc_structure"], root)
        if "acc_coordination" in bundle_files:
            files["acc_coordination"] = validate_acc_coordination_file(bundle_files["acc_coordination"], root)
        if "definitions" in bundle_files:
            files["definitions"] = validate_sector_definitions_file(bundle_files["definitions"], root)
    else:
        missing_kinds = [kind for kind in TMA_REQUIRED_KINDS if kind not in bundle_files]
        if missing_kinds:
            raise ValueError(f"{bundle_repo_path}: missing sector bundle files: {', '.join(missing_kinds)}")
        files["tma_structure"] = validate_tma_structure_file(bundle_files["tma_structure"], root)
        files["definitions"] = validate_sector_definitions_file(bundle_files["definitions"], root)
        if "tma_coordination" in bundle_files:
            files["tma_coordination"] = validate_tma_coordination_file(bundle_files["tma_coordination"], root)

        documents = {
            kind: json.loads(bundle_files[kind].read_text(encoding="utf-8"))
            for kind in ("tma_structure", "definitions")
        }
        if any("airac_overrides" in document for document in documents.values()):
            for tier in ("", *airac_overrides.TIERS):
                resolved = {kind: airac_overrides.resolve(document, tier) for kind, document in documents.items()}
                defs_rows = resolved["definitions"].get(
                    "sector_definitions",
                    resolved["definitions"].get("definitions", resolved["definitions"].get("sectors", [])),
                )
                defined: set[str] = set()
                for row in defs_rows:
                    if isinstance(row, dict):
                        defined.update(_definition_sector_ids(row, bundle_files["definitions"]))
                referenced = _referenced_tma_sectors(resolved["tma_structure"])
                if referenced - defined:
                    raise ValueError(
                        f"{bundle_dir}: {tier or 'shared default'} references undefined sectors: "
                        f"{sorted(referenced - defined)}"
                    )

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
    for legacy_name in LEGACY_GENERATED_FILE_NAMES:
        legacy_paths = content_files(root, legacy_name)
        if legacy_paths:
            raise ValueError(
                f"{safe_repo_path(legacy_paths[0], root)}: {legacy_name} is generated at publish and must not exist in source"
            )

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
