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
import misc_drawings_manifest
import routes_release_manifest
import runway_configs_manifest
import sector_data_manifest
import color_profiles_manifest
import airac_overrides
import release_gates
import routes_full_feed
from legacy_contract import LEGACY_DATASET_MANIFEST_SCHEMA_VERSION, LEGACY_RELEASE_MANIFEST_SCHEMA_VERSION


REPO_NAME = "lainoa-software/voiceatc-simulator-community"
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


def _full_asset_name(asset_name: str) -> str:
    """The full-feed asset beside a default zip: ``mva-2609.zip`` -> ``mva-2609-full.zip``."""
    stem, dot, suffix = asset_name.rpartition(".")
    return f"{stem}-full.{suffix}" if dot else f"{asset_name}-full"


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
    archive_sources = {repo_path: repo_path for repo_path in repo_paths}
    return build_deterministic_zip_from_sources(root, archive_sources, output_path)


def build_deterministic_zip_from_sources(
    root: Path,
    archive_sources: dict[str, str],
    output_path: Path,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_sources: dict[str, str] = {}
    for raw_archive_path, raw_source_path in archive_sources.items():
        archive_path = _safe_repo_paths([raw_archive_path], output_path.name)[0]
        source_path = _safe_repo_paths([raw_source_path], output_path.name)[0]
        if archive_path in normalized_sources:
            raise ValueError(f"{output_path.name}: duplicate archive path '{archive_path}'")
        normalized_sources[archive_path] = source_path
    for source_repo_path in normalized_sources.values():
        if not (root / source_repo_path).is_file():
            raise ValueError(f"Missing release asset source file: {source_repo_path}")
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for archive_path in sorted(normalized_sources):
            source_repo_path = normalized_sources[archive_path]
            source_path = root / source_repo_path
            info = zipfile.ZipInfo(archive_path, date_time=ZIP_TIMESTAMP)
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
    airports: dict[str, object] | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    if airports is None:
        base_manifest = mva_manifest.build_manifest(root, commit_sha=commit_sha)
        airports = base_manifest["airports"]
    return {
        "schema_version": LEGACY_DATASET_MANIFEST_SCHEMA_VERSION,
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
    airports: dict[str, object] | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    if airports is None:
        base_manifest = runway_configs_manifest.build_manifest(root, commit_sha=commit_sha)
        airports = base_manifest["airports"]
    return {
        "schema_version": LEGACY_DATASET_MANIFEST_SCHEMA_VERSION,
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
    bundles: dict[str, object] | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    if bundles is None:
        base_manifest = sector_data_manifest.build_manifest(root, commit_sha=commit_sha)
        bundles = base_manifest["bundles"]
    return {
        "schema_version": LEGACY_DATASET_MANIFEST_SCHEMA_VERSION,
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


def build_misc_drawings_release_manifest(
    *,
    release_tag: str,
    asset_name: str,
    download_url: str,
    published_at: str,
    commit_sha: str,
    asset_sha256: str,
    asset_size_bytes: int,
    airports: dict[str, object] | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    if airports is None:
        base_manifest = misc_drawings_manifest.build_manifest(root, commit_sha=commit_sha)
        airports = base_manifest["airports"]
    return {
        "schema_version": LEGACY_DATASET_MANIFEST_SCHEMA_VERSION,
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


def build_color_profiles_release_manifest(
    *,
    release_tag: str,
    asset_name: str,
    download_url: str,
    published_at: str,
    commit_sha: str,
    asset_sha256: str,
    asset_size_bytes: int,
    profiles: dict[str, object] | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    resolved_profiles = profiles
    if resolved_profiles is None:
        projection = color_profiles_manifest.build_release_projection(root, commit_sha=commit_sha)
        resolved_profiles = projection["profiles"]
    return {
        "schema_version": LEGACY_DATASET_MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag.strip(),
        "commit_sha": commit_sha.strip(),
        "asset_name": asset_name.strip(),
        "download_url": download_url.strip(),
        "sha256": asset_sha256.strip(),
        "size_bytes": int(asset_size_bytes),
        "profile_count": len(resolved_profiles),
        "published_at": published_at.strip(),
        "profiles": resolved_profiles,
    }


def build_release_manifest(
    routes_manifest: dict[str, object],
    mva_release_manifest: dict[str, object],
    runway_release_manifest: dict[str, object],
    sector_data_release_manifest: dict[str, object],
    misc_drawings_release_manifest: dict[str, object],
    color_profiles_release_manifest: dict[str, object],
    published_at: str,
    release_title: str | None = None,
) -> dict[str, object]:
    release_tag = str(routes_manifest.get("release_tag", "")).strip()
    resolved_release_title = release_title.strip() if release_title and release_title.strip() else _build_release_title(release_tag)
    assets = {
        "routes_tsv": {
            "repo_path": "ROUTES/routes_legacy.tsv",
            "airac": str(routes_manifest.get("airac", "")).strip(),
            "source_airac": str(routes_manifest.get("source_airac", "")).strip(),
            "compatibility_fallback": bool(routes_manifest.get("compatibility_fallback", False)),
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
        "misc_drawings_zip": {
            "asset_name": str(misc_drawings_release_manifest.get("asset_name", "")).strip(),
            "download_url": str(misc_drawings_release_manifest.get("download_url", "")).strip(),
            "sha256": str(misc_drawings_release_manifest.get("sha256", "")).strip(),
            "size_bytes": int(misc_drawings_release_manifest.get("size_bytes", 0)),
            "airport_count": int(misc_drawings_release_manifest.get("airport_count", 0)),
            "content_type": "application/zip",
            "preserves_repo_paths": True,
        },
        "color_profiles_zip": {
            "asset_name": str(color_profiles_release_manifest.get("asset_name", "")).strip(),
            "download_url": str(color_profiles_release_manifest.get("download_url", "")).strip(),
            "sha256": str(color_profiles_release_manifest.get("sha256", "")).strip(),
            "size_bytes": int(color_profiles_release_manifest.get("size_bytes", 0)),
            "profile_count": int(color_profiles_release_manifest.get("profile_count", 0)),
            "content_type": "application/zip",
            "preserves_repo_paths": True,
        },
    }
    rich = routes_manifest.get("rich_routes_tsv")
    if isinstance(rich, dict):
        assets["routes_rich_tsv"] = {
            "repo_path": "ROUTES/routes.tsv",
            "airac": str(routes_manifest.get("airac", "")).strip(),
            "asset_name": str(rich.get("asset_name", "")).strip(),
            "download_url": str(rich.get("download_url", "")).strip(),
            "sha256": str(rich.get("sha256", "")).strip(),
            "size_bytes": int(rich.get("size_bytes", 0)),
            "route_count": int(rich.get("route_count", 0)),
            "projection_id": str(rich.get("projection_id", "")).strip(),
            "content_type": "text/tab-separated-values; charset=utf-8",
        }
    return {
        "schema_version": LEGACY_RELEASE_MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag,
        "release_title": resolved_release_title,
        "commit_sha": str(routes_manifest.get("commit_sha", "")).strip(),
        "published_at": published_at.strip(),
        "airac": str(routes_manifest.get("airac", "")).strip(),
        "assets": assets,
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
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    routes_distribution = routes_release_manifest.validate_routes_distribution(root)
    airac = str(routes_distribution["rich"]["airac"])

    routes_asset_name = f"routes-{airac}.tsv"
    routes_rich_asset_name = f"routes-rich-{airac}.tsv"
    mva_asset_name = f"mva-{airac}.zip"
    runway_asset_name = f"runway-configs-{airac}.zip"
    sector_data_asset_name = f"sector-data-{airac}.zip"
    misc_drawings_asset_name = f"misc-drawings-{airac}.zip"
    color_profiles_asset_name = f"color-profiles-{airac}.zip"

    routes_source_path = root / "ROUTES" / "routes_legacy.tsv"
    routes_asset_path = output_dir / routes_asset_name
    shutil.copyfile(routes_source_path, routes_asset_path)
    routes_rich_source_path = root / "ROUTES" / "routes.tsv"
    routes_rich_asset_path = output_dir / routes_rich_asset_name
    shutil.copyfile(routes_rich_source_path, routes_rich_asset_path)

    mva_base_manifest = mva_manifest.build_manifest(root, commit_sha=commit_sha)
    runway_base_manifest = runway_configs_manifest.build_manifest(root, commit_sha=commit_sha)
    sector_data_base_manifest = sector_data_manifest.build_manifest(root, commit_sha=commit_sha)
    misc_drawings_base_manifest = misc_drawings_manifest.build_manifest(root, commit_sha=commit_sha)
    color_profiles_projection = color_profiles_manifest.build_release_projection(root, commit_sha=commit_sha)

    # Channel gates: the default view (what every live build reads) drops gated
    # entries (any `requires`, or channels short of all three); the full view keeps them all.
    gates = release_gates.load_gates(root)
    color_archive_sources = color_profiles_projection["archive_sources"]
    gated = {
        "mva": release_gates.apply_gates(
            "mva", mva_base_manifest["airports"], gates=gates
        ),
        "runway_configs": release_gates.apply_gates(
            "runway_configs", runway_base_manifest["airports"], gates=gates
        ),
        "sector_data": release_gates.apply_gates(
            "sector_data", sector_data_base_manifest["bundles"], gates=gates
        ),
        "misc_drawings": release_gates.apply_gates(
            "misc_drawings", misc_drawings_base_manifest["airports"], gates=gates
        ),
        "color_profiles": release_gates.apply_gates(
            "color_profiles",
            color_profiles_projection["profiles"],
            gates=gates,
            archive_sources=color_archive_sources,
            required_kinds=("colors",),
        ),
    }
    for dataset in ("mva", "runway_configs", "misc_drawings"):
        airac_overrides.project_feed(root, gated[dataset])
    sector_default_sources, sector_full_sources = airac_overrides.project_sector_feed(root, gated["sector_data"])
    mva_airports = gated["mva"]["default"]
    runway_airports = gated["runway_configs"]["default"]
    sector_data_bundles = gated["sector_data"]["default"]
    misc_drawings_airports = gated["misc_drawings"]["default"]
    color_profiles = gated["color_profiles"]["default"]
    color_default_paths = set(release_gates.entry_repo_paths(color_profiles))
    color_default_sources = {
        archive_path: source_path
        for archive_path, source_path in color_archive_sources.items()
        if archive_path in color_default_paths
    }

    mva_repo_paths = sorted({str(entry["repo_path"]) for entry in mva_airports.values()})
    runway_repo_paths = [str(entry["repo_path"]) for entry in runway_airports.values()]
    misc_drawings_repo_paths = sorted({str(entry["repo_path"]) for entry in misc_drawings_airports.values()})
    mva_asset = build_deterministic_zip(root, mva_repo_paths, output_dir / mva_asset_name)
    runway_asset = build_deterministic_zip(root, runway_repo_paths, output_dir / runway_asset_name)
    sector_data_asset = build_deterministic_zip_from_sources(root, sector_default_sources, output_dir / sector_data_asset_name)
    misc_drawings_asset = build_deterministic_zip(root, misc_drawings_repo_paths, output_dir / misc_drawings_asset_name)
    color_profiles_asset = build_deterministic_zip_from_sources(
        root,
        color_default_sources,
        output_dir / color_profiles_asset_name,
    )

    full_assets = {
        "mva": build_deterministic_zip(
            root,
            airac_overrides.full_repo_paths(gated["mva"]),
            output_dir / _full_asset_name(mva_asset_name),
        ),
        "runway_configs": build_deterministic_zip(
            root,
            airac_overrides.full_repo_paths(gated["runway_configs"]),
            output_dir / _full_asset_name(runway_asset_name),
        ),
        "sector_data": build_deterministic_zip_from_sources(
            root,
            sector_full_sources,
            output_dir / _full_asset_name(sector_data_asset_name),
        ),
        "misc_drawings": build_deterministic_zip(
            root,
            airac_overrides.full_repo_paths(gated["misc_drawings"]),
            output_dir / _full_asset_name(misc_drawings_asset_name),
        ),
        "color_profiles": build_deterministic_zip_from_sources(
            root,
            color_archive_sources,
            output_dir / _full_asset_name(color_profiles_asset_name),
        ),
    }
    full_manifests = {
        dataset: release_gates.build_full_manifest(
            dataset=dataset,
            full_entries=gated[dataset]["full_entries"],
            repo=REPO_NAME,
            release_tag=release_tag,
            commit_sha=commit_sha,
            published_at=published_at,
            asset=asset,
            download_url=_download_url(download_repo, release_tag, str(asset["asset_name"])),
        )
        for dataset, asset in full_assets.items()
    }
    # Gated route overlays (ROUTES/full/*.tsv): full-feed variants only. The default
    # routes tables, manifests and assets below never see them.
    routes_full_entries, routes_full_assets = routes_full_feed.build_full_routes(
        root=root,
        output_dir=output_dir,
        download_url_for=lambda name: _download_url(download_repo, release_tag, name),
    )
    full_manifests["routes"] = release_gates.build_full_manifest(
        dataset="routes",
        full_entries=routes_full_entries,
        repo=REPO_NAME,
        release_tag=release_tag,
        commit_sha=commit_sha,
        published_at=published_at,
        asset=None,
    )

    routes_manifest =routes_release_manifest.build_routes_manifest(
        release_tag=release_tag,
        asset_name=routes_asset_name,
        download_url=_download_url(download_repo, release_tag, routes_asset_name),
        published_at=published_at,
        commit_sha=commit_sha,
        rich_asset_name=routes_rich_asset_name,
        rich_download_url=_download_url(
            download_repo,
            release_tag,
            routes_rich_asset_name,
        ),
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
        airports=mva_airports,
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
        airports=runway_airports,
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
        bundles=sector_data_bundles,
        root=root,
    )
    misc_drawings_release_manifest = build_misc_drawings_release_manifest(
        release_tag=release_tag,
        asset_name=misc_drawings_asset_name,
        download_url=_download_url(download_repo, release_tag, misc_drawings_asset_name),
        published_at=published_at,
        commit_sha=commit_sha,
        asset_sha256=str(misc_drawings_asset["sha256"]),
        asset_size_bytes=int(misc_drawings_asset["size_bytes"]),
        airports=misc_drawings_airports,
        root=root,
    )
    color_profiles_release_manifest = build_color_profiles_release_manifest(
        release_tag=release_tag,
        asset_name=color_profiles_asset_name,
        download_url=_download_url(download_repo, release_tag, color_profiles_asset_name),
        published_at=published_at,
        commit_sha=commit_sha,
        asset_sha256=str(color_profiles_asset["sha256"]),
        asset_size_bytes=int(color_profiles_asset["size_bytes"]),
        profiles=color_profiles,
        root=root,
    )
    release_manifest = build_release_manifest(
        routes_manifest,
        mva_release_manifest,
        runway_release_manifest,
        sector_data_release_manifest,
        misc_drawings_release_manifest,
        color_profiles_release_manifest,
        published_at,
        release_title=release_title,
    )

    release_manifest_asset_path = output_dir / RELEASE_MANIFEST_ASSET_NAME
    _write_json(release_manifest_asset_path, release_manifest)

    return {
        "airac": airac,
        "assets": {
            "routes_tsv": {
                "asset_name": routes_asset_name,
                "path": str(routes_asset_path),
                "sha256": str(routes_manifest["sha256"]),
                "size_bytes": int(routes_manifest["size_bytes"]),
            },
            "routes_rich_tsv": {
                "asset_name": routes_rich_asset_name,
                "path": str(routes_rich_asset_path),
                "sha256": str(routes_manifest["rich_routes_tsv"]["sha256"]),
                "size_bytes": int(routes_manifest["rich_routes_tsv"]["size_bytes"]),
            },
            "mva_zip": mva_asset,
            "runway_configs_zip": runway_asset,
            "sector_data_zip": sector_data_asset,
            "misc_drawings_zip": misc_drawings_asset,
            "color_profiles_zip": color_profiles_asset,
            **{f"{dataset}_full_zip": asset for dataset, asset in full_assets.items()},
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
            "misc_drawings": misc_drawings_release_manifest,
            "color_profiles": color_profiles_release_manifest,
            "release": release_manifest,
        },
        "full_manifests": full_manifests,
        # Every full-feed asset to upload, by dataset (zip datasets: one; routes: one per variant).
        "full_assets": {
            **{dataset: [asset] for dataset, asset in full_assets.items()},
            "routes": routes_full_assets,
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
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
