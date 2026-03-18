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
ROUTES_PATH = ROOT / "ROUTES" / "routes.tsv"
ROUTES_MANIFEST_PATH = ROOT / ".voiceatc" / "routes_manifest.json"
RELEASE_MANIFEST_PATH = ROOT / ".voiceatc" / "release_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
SCHEMA_VERSION = 1
RELEASE_TITLE_PREFIX = "Daily Community Cache"


def current_commit_sha(root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()


def parse_routes_file(root: Path = ROOT) -> dict[str, object]:
    raw_bytes = ROUTES_PATH.read_bytes() if root == ROOT else (root / "ROUTES" / "routes.tsv").read_bytes()
    route_path = ROUTES_PATH if root == ROOT else (root / "ROUTES" / "routes.tsv")
    text = raw_bytes.decode("utf-8-sig")
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"{route_path}: file is empty")

    header = lines[0].strip()
    if not header.lower().startswith("airac "):
        raise ValueError(f"{route_path}: first line must be 'airac <cycle>'")

    airac = header[6:].strip()
    if not airac.isdigit() or len(airac) != 4:
        raise ValueError(f"{route_path}: invalid AIRAC cycle '{airac}'")

    route_count = 0
    for line_number, raw_line in enumerate(lines[1:], start=2):
        line = raw_line.rstrip("\r\n")
        if not line.strip() or line.upper().startswith("ORIGIN"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise ValueError(f"{route_path}:{line_number}: expected at least 3 tab-separated columns")
        origin = parts[0].strip().upper()
        dest = parts[1].strip().upper()
        full_route = parts[2].strip().upper()
        if not origin or not dest:
            raise ValueError(f"{route_path}:{line_number}: origin and dest must be non-empty")
        if not full_route:
            continue
        route_count += 1

    if route_count <= 0:
        raise ValueError(f"{route_path}: no route rows found")

    return {
        "airac": airac,
        "route_count": route_count,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def build_routes_manifest(
    *,
    release_tag: str,
    asset_name: str,
    download_url: str,
    published_at: str,
    commit_sha: str,
    root: Path = ROOT,
) -> dict[str, object]:
    if not release_tag.strip():
        raise ValueError("release_tag must not be empty")
    if not asset_name.strip():
        raise ValueError("asset_name must not be empty")
    if not download_url.strip():
        raise ValueError("download_url must not be empty")
    if not commit_sha.strip():
        raise ValueError("commit_sha must not be empty")

    routes = parse_routes_file(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag.strip(),
        "commit_sha": commit_sha.strip(),
        "airac": str(routes["airac"]),
        "asset_name": asset_name.strip(),
        "download_url": download_url.strip(),
        "sha256": str(routes["sha256"]),
        "size_bytes": int(routes["size_bytes"]),
        "route_count": int(routes["route_count"]),
        "published_at": published_at.strip(),
    }


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


def build_release_manifest(
    routes_manifest: dict[str, object],
    published_at: str,
    release_title: str | None = None,
) -> dict[str, object]:
    release_tag = str(routes_manifest.get("release_tag", "")).strip()
    published = published_at.strip()
    resolved_release_title = release_title.strip() if release_title and release_title.strip() else _build_release_title(release_tag)

    return {
        "schema_version": SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag,
        "release_title": resolved_release_title,
        "commit_sha": str(routes_manifest.get("commit_sha", "")).strip(),
        "published_at": published,
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
            }
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ROUTES/routes.tsv and write GitHub-release-backed community manifests.")
    parser.add_argument("--write", action="store_true", help="Write .voiceatc/routes_manifest.json and .voiceatc/release_manifest.json")
    parser.add_argument("--validate-only", action="store_true", help="Validate ROUTES/routes.tsv without writing manifests")
    parser.add_argument("--release-tag", default="", help="Release tag, for example daily-2026-03-15")
    parser.add_argument("--release-title", default="", help="Release title, for example Daily Community Cache - Saturday 2026-03-15")
    parser.add_argument("--asset-name", default="", help="Release asset name, for example routes-2602.tsv")
    parser.add_argument("--download-url", default="", help="Full release asset download URL")
    parser.add_argument("--published-at", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    parser.add_argument("--commit-sha", default="", help="Source commit SHA for the published release")
    args = parser.parse_args()

    try:
        routes = parse_routes_file()
        if args.validate_only and not args.write:
            print(f"Validated routes.tsv: AIRAC {routes['airac']} with {routes['route_count']} rows.")
            return 0

        commit_sha = args.commit_sha.strip() or current_commit_sha()
        routes_manifest = build_routes_manifest(
            release_tag=args.release_tag,
            asset_name=args.asset_name,
            download_url=args.download_url,
            published_at=args.published_at,
            commit_sha=commit_sha,
        )
        release_manifest = build_release_manifest(
            routes_manifest,
            args.published_at,
            release_title=args.release_title.strip() or None,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.write:
        ROUTES_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        ROUTES_MANIFEST_PATH.write_text(json.dumps(routes_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        RELEASE_MANIFEST_PATH.write_text(json.dumps(release_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote {ROUTES_MANIFEST_PATH.relative_to(ROOT).as_posix()}")
        print(f"Wrote {RELEASE_MANIFEST_PATH.relative_to(ROOT).as_posix()}")
        return 0

    print(json.dumps({"routes_manifest": routes_manifest, "release_manifest": release_manifest}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
