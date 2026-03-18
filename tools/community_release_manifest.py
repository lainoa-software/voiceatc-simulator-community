#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import mva_manifest
import routes_release_manifest
import runway_configs_manifest
import sector_data_manifest


REPO_NAME = "lainoa-software/voiceatc-simulator-community"
RELEASE_MANIFEST_SCHEMA_VERSION = 2
DATASET_MANIFEST_SCHEMA_VERSION = 2
RELEASE_MANIFEST_PATH = ROOT / ".voiceatc" / "release_manifest.json"
RELEASE_MANIFEST_ASSET_NAME = "release-manifest.json"
RELEASE_TITLE_PREFIX = "Daily Community Release"
ZIP_TIMESTAMP = (2024, 1, 1, 0, 0, 0)
ZIP_FILE_MODE = 0o100644 << 16


def _hash_bytes(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def _download_url(download_repo: str, release_tag: str, asset_name: str) -> str:
    return f"https://github.com/{download_repo}/releases/download/{release_tag}/{asset_name}"


def _build_release_title(release_tag: str) -> str:
    normalized_tag = release_tag.strip()
    if not normalized_tag.startswith("daily-"):
        raise ValueError(f"release_tag must match 'daily-YYYY-MM-DD[-suffix]': {release_tag}")

    tag_body = normalized_tag.removeprefix("daily-")
    if len(tag_body) < 10:
        raise ValueError(f"release_tag must match 'daily-YYYY-MM-DD[-suffix]': {release_tag}")

    date_text = tag_body[:10]
    suffix = ""
    if len(tag_body) > 10:
        if tag_body[10] != "-":
            raise ValueError(f"release_tag must match 'daily-YYYY-MM-DD[-suffix]': {release_tag}")
        suffix = tag_body[11:].strip()
        if not suffix or not suffix.isalpha() or suffix.lower() != suffix:
            raise ValueError(f"release_tag suffix must be lowercase letters: {release_tag}")

    try:
        title_date = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"release_tag must match 'daily-YYYY-MM-DD[-suffix]': {release_tag}") from exc

    title = f"{RELEASE_TITLE_PREFIX} - {title_date.strftime('%A')} {date_text}"
    if suffix:
        title = f"{title} {suffix}"
    return title


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_repo_paths(paths: list[str], dataset_label: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in sorted(paths):
        repo_path = str(raw_path).strip().replace("\\", "/")
        if not repo_path or repo_path.startswith("/") or repo_path.startswith("../") or "/../" in repo_path:
            raise ValueError(f"{dataset_label}: invalid repo_path '{raw_path}'")
        if repo_path in seen:
            raise ValueError(f"{dataset_label}: duplicate repo_path '{repo_path}'")
        seen.add(repo_path)
        normalized.append(repo_path)
    return normalized


def build_deterministic_zip(root: Path, repo_paths: list[str], output_path: Path) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_paths = _safe_repo_paths(repo_paths, output_path.name)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for repo_path in normalized_paths:
            source_path = root / repo_path
            if not source_path.is_file():
                raise ValueError(f"Missing release asset source file: {repo_path}")
            info = zipfile.ZipInfo(repo_path, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = ZIP_FILE_MODE
            archive.writestr(info, source_path.read_bytes())

    raw_bytes = output_path.read_bytes()
    return {
        "asset_name": output_path.name,
        "path": str(output_path),
        "sha256": _hash_bytes(raw_bytes),
        "size_bytes": len(raw_bytes),
    }


def build_mva_release_manifest(
    *,
    release_tag: str,
    asset_name: str,
    download_url: str,
    published_at: str,
    commit_sha: str,
    asset_sha256: str,
    asset_size_bytes: int,
    root: Path = ROOT,
) -> dict[str, object]:
    base_manifest = mva_manifest.build_manifest(root, commit_sha=commit_sha)
    airports = base_manifest["airports"]
    return {
        "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag.strip(),
        "commit_sha": commit_sha.strip(),
        "asset_name": asset_name.strip(),
        "download_url": download_url.strip(),
        "sha256": asset_sha256.strip(),
        "size_bytes": int(asset_size_bytes),
        "airport_count": len(airports),
        "published_at": published_at.strip(),
        "airports": airports,
    }


def build_runway_release_manifest(
    *,
    release_tag: str,
    asset_name: str,
    download_url: str,
    published_at: str,
    commit_sha: str,
    asset_sha256: str,
    asset_size_bytes: int,
    root: Path = ROOT,
) -> dict[str, object]:
    base_manifest = runway_configs_manifest.build_manifest(root, commit_sha=commit_sha)
    airports = base_manifest["airports"]
    return {
        "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag.strip(),
        "commit_sha": commit_sha.strip(),
        "asset_name": asset_name.strip(),
        "download_url": download_url.strip(),
        "sha256": asset_sha256.strip(),
        "size_bytes": int(asset_size_bytes),
        "airport_count": len(airports),
        "published_at": published_at.strip(),
        "airports": airports,
    }


def build_sector_data_release_manifest(
    *,
    release_tag: str,
    asset_name: str,
    download_url: str,
    published_at: str,
    commit_sha: str,
    asset_sha256: str,
    asset_size_bytes: int,
    root: Path = ROOT,
) -> dict[str, object]:
    base_manifest = sector_data_manifest.build_manifest(root, commit_sha=commit_sha)
    bundles = base_manifest["bundles"]
    return {
        "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag.strip(),
        "commit_sha": commit_sha.strip(),
        "asset_name": asset_name.strip(),
        "download_url": download_url.strip(),
        "sha256": asset_sha256.strip(),
        "size_bytes": int(asset_size_bytes),
        "bundle_count": len(bundles),
        "published_at": published_at.strip(),
        "bundles": bundles,
    }


def build_release_manifest(
    routes_manifest: dict[str, object],
    mva_release_manifest: dict[str, object],
    runway_release_manifest: dict[str, object],
    sector_data_release_manifest: dict[str, object],
    published_at: str,
    release_title: str | None = None,
) -> dict[str, object]:
    release_tag = str(routes_manifest.get("release_tag", "")).strip()
    resolved_release_title = release_title.strip() if release_title and release_title.strip() else _build_release_title(release_tag)
    return {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag,
        "release_title": resolved_release_title,
        "commit_sha": str(routes_manifest.get("commit_sha", "")).strip(),
        "published_at": published_at.strip(),
        "airac": str(routes_manifest.get("airac", "")).strip(),
        "assets": {
            "routes_tsv": {
                "repo_path": "ROUTES/routes.tsv",
                "airac": str(routes_manifest.get("airac", "")).strip(),
                "asset_name": str(routes_manifest.get("asset_name", "")).strip(),
                "download_url": str(routes_manifest.get("download_url", "")).strip(),
                "sha256": str(routes_manifest.get("sha256", "")).strip(),
                "size_bytes": int(routes_manifest.get("size_bytes", 0)),
                "route_count": int(routes_manifest.get("route_count", 0)),
                "content_type": "text/tab-separated-values; charset=utf-8",
            },
            "mva_zip": {
                "asset_name": str(mva_release_manifest.get("asset_name", "")).strip(),
                "download_url": str(mva_release_manifest.get("download_url", "")).strip(),
                "sha256": str(mva_release_manifest.get("sha256", "")).strip(),
                "size_bytes": int(mva_release_manifest.get("size_bytes", 0)),
                "airport_count": int(mva_release_manifest.get("airport_count", 0)),
                "content_type": "application/zip",
                "preserves_repo_paths": True,
            },
            "runway_configs_zip": {
                "asset_name": str(runway_release_manifest.get("asset_name", "")).strip(),
                "download_url": str(runway_release_manifest.get("download_url", "")).strip(),
                "sha256": str(runway_release_manifest.get("sha256", "")).strip(),
                "size_bytes": int(runway_release_manifest.get("size_bytes", 0)),
                "airport_count": int(runway_release_manifest.get("airport_count", 0)),
                "content_type": "application/zip",
                "preserves_repo_paths": True,
            },
            "sector_data_zip": {
                "asset_name": str(sector_data_release_manifest.get("asset_name", "")).strip(),
                "download_url": str(sector_data_release_manifest.get("download_url", "")).strip(),
                "sha256": str(sector_data_release_manifest.get("sha256", "")).strip(),
                "size_bytes": int(sector_data_release_manifest.get("size_bytes", 0)),
                "bundle_count": int(sector_data_release_manifest.get("bundle_count", 0)),
                "content_type": "application/zip",
                "preserves_repo_paths": True,
            },
        },
    }


def build_release_bundle(
    *,
    output_dir: Path,
    release_tag: str,
    published_at: str,
    commit_sha: str,
    download_repo: str,
    release_title: str | None = None,
    root: Path = ROOT,
    write_manifests: bool = False,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    routes_info = routes_release_manifest.parse_routes_file(root)
    airac = str(routes_info["airac"])

    routes_asset_name = f"routes-{airac}.tsv"
    mva_asset_name = f"mva-{airac}.zip"
    runway_asset_name = f"runway-configs-{airac}.zip"
    sector_data_asset_name = f"sector-data-{airac}.zip"

    routes_source_path = root / "ROUTES" / "routes.tsv"
    routes_asset_path = output_dir / routes_asset_name
    shutil.copyfile(routes_source_path, routes_asset_path)

    mva_base_manifest = mva_manifest.build_manifest(root, commit_sha=commit_sha)
    runway_base_manifest = runway_configs_manifest.build_manifest(root, commit_sha=commit_sha)
    sector_data_base_manifest = sector_data_manifest.build_manifest(root, commit_sha=commit_sha)

    mva_repo_paths = [str(entry["repo_path"]) for entry in mva_base_manifest["airports"].values()]
    runway_repo_paths = [str(entry["repo_path"]) for entry in runway_base_manifest["airports"].values()]
    sector_data_repo_paths = [
        str(file_entry["repo_path"])
        for bundle in sector_data_base_manifest["bundles"].values()
        for file_entry in bundle["files"].values()
    ]

    mva_asset = build_deterministic_zip(root, mva_repo_paths, output_dir / mva_asset_name)
    runway_asset = build_deterministic_zip(root, runway_repo_paths, output_dir / runway_asset_name)
    sector_data_asset = build_deterministic_zip(root, sector_data_repo_paths, output_dir / sector_data_asset_name)

    routes_manifest = routes_release_manifest.build_routes_manifest(
        release_tag=release_tag,
        asset_name=routes_asset_name,
        download_url=_download_url(download_repo, release_tag, routes_asset_name),
        published_at=published_at,
        commit_sha=commit_sha,
        root=root,
    )
    mva_release_manifest = build_mva_release_manifest(
        release_tag=release_tag,
        asset_name=mva_asset_name,
        download_url=_download_url(download_repo, release_tag, mva_asset_name),
        published_at=published_at,
        commit_sha=commit_sha,
        asset_sha256=str(mva_asset["sha256"]),
        asset_size_bytes=int(mva_asset["size_bytes"]),
        root=root,
    )
    runway_release_manifest = build_runway_release_manifest(
        release_tag=release_tag,
        asset_name=runway_asset_name,
        download_url=_download_url(download_repo, release_tag, runway_asset_name),
        published_at=published_at,
        commit_sha=commit_sha,
        asset_sha256=str(runway_asset["sha256"]),
        asset_size_bytes=int(runway_asset["size_bytes"]),
        root=root,
    )
    sector_data_release_manifest = build_sector_data_release_manifest(
        release_tag=release_tag,
        asset_name=sector_data_asset_name,
        download_url=_download_url(download_repo, release_tag, sector_data_asset_name),
        published_at=published_at,
        commit_sha=commit_sha,
        asset_sha256=str(sector_data_asset["sha256"]),
        asset_size_bytes=int(sector_data_asset["size_bytes"]),
        root=root,
    )
    release_manifest = build_release_manifest(
        routes_manifest,
        mva_release_manifest,
        runway_release_manifest,
        sector_data_release_manifest,
        published_at,
        release_title=release_title,
    )

    release_manifest_asset_path = output_dir / RELEASE_MANIFEST_ASSET_NAME
    _write_json(release_manifest_asset_path, release_manifest)

    if write_manifests:
        _write_json(routes_release_manifest.ROUTES_MANIFEST_PATH, routes_manifest)
        _write_json(mva_manifest.MANIFEST_PATH, mva_release_manifest)
        _write_json(runway_configs_manifest.MANIFEST_PATH, runway_release_manifest)
        _write_json(sector_data_manifest.MANIFEST_PATH, sector_data_release_manifest)
        _write_json(RELEASE_MANIFEST_PATH, release_manifest)

    return {
        "airac": airac,
        "assets": {
            "routes_tsv": {
                "asset_name": routes_asset_name,
                "path": str(routes_asset_path),
                "sha256": str(routes_manifest["sha256"]),
                "size_bytes": int(routes_manifest["size_bytes"]),
            },
            "mva_zip": mva_asset,
            "runway_configs_zip": runway_asset,
            "sector_data_zip": sector_data_asset,
            "release_manifest": {
                "asset_name": RELEASE_MANIFEST_ASSET_NAME,
                "path": str(release_manifest_asset_path),
                "sha256": _hash_bytes(release_manifest_asset_path.read_bytes()),
                "size_bytes": release_manifest_asset_path.stat().st_size,
            },
        },
        "manifests": {
            "routes": routes_manifest,
            "mva": mva_release_manifest,
            "runway_configs": runway_release_manifest,
            "sector_data": sector_data_release_manifest,
            "release": release_manifest,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic daily community release assets and manifests.")
    parser.add_argument("--output-dir", required=True, help="Directory where release assets will be written")
    parser.add_argument("--release-tag", required=True, help="Release tag, for example daily-2026-03-18")
    parser.add_argument("--release-title", default="", help="Release title, for example Daily Community Release - Wednesday 2026-03-18")
    parser.add_argument("--published-at", required=True, help="Release timestamp in UTC")
    parser.add_argument("--commit-sha", default="", help="Source commit SHA for the published release")
    parser.add_argument("--download-repo", default=REPO_NAME, help="GitHub repo used in release asset URLs")
    parser.add_argument("--write-manifests", action="store_true", help="Write .voiceatc manifests in-place")
    args = parser.parse_args()

    try:
        commit_sha = args.commit_sha.strip() or routes_release_manifest.current_commit_sha(ROOT)
        bundle = build_release_bundle(
            output_dir=Path(args.output_dir),
            release_tag=args.release_tag.strip(),
            published_at=args.published_at.strip(),
            commit_sha=commit_sha,
            download_repo=args.download_repo.strip() or REPO_NAME,
            release_title=args.release_title.strip() or None,
            root=ROOT,
            write_manifests=args.write_manifests,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
