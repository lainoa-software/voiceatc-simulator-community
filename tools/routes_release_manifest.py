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
ROUTES_PATH = ROOT / "ROUTES" / "routes.tsv"
ROUTES_DEFAULT_PATH = ROOT / "ROUTES" / "routes_default.tsv"
ROUTES_DEFAULT_MANIFEST_PATH = ROOT / "ROUTES" / "routes_default_manifest.json"
ROUTES_MANIFEST_PATH = ROOT / ".voiceatc" / "routes_manifest.json"
RELEASE_MANIFEST_PATH = ROOT / ".voiceatc" / "release_manifest.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"
ROUTES_MANIFEST_SCHEMA_VERSION = 2
RELEASE_MANIFEST_SCHEMA_VERSION = 1
RELEASE_TITLE_PREFIX = "Daily Community Release"
BUNDLED_DEFAULT_AIRAC = "2503"
BUNDLED_DEFAULT_MANIFEST_SCHEMA_VERSION = 1
RUNWAY_THRESHOLD_IDENT_RE = re.compile(r"^RW(?:0[1-9]|[12][0-9]|3[0-6])[LCR]?$")


def current_commit_sha(root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()


def _parse_routes_tsv(route_path: Path) -> dict[str, object]:
    raw_bytes = route_path.read_bytes()
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
    source_airac = ""
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
        creation_airac = parts[3].strip() if len(parts) >= 4 else ""
        if creation_airac:
            if not creation_airac.isdigit() or len(creation_airac) != 4:
                raise ValueError(
                    f"{route_path}:{line_number}: invalid CREATION_AIRAC '{creation_airac}'"
                )
            if creation_airac > airac:
                raise ValueError(
                    f"{route_path}:{line_number}: CREATION_AIRAC {creation_airac} "
                    f"must not be newer than declared AIRAC {airac}"
                )
            source_airac = max(source_airac, creation_airac)
        if not full_route:
            continue
        runway_tokens = [
            token
            for token in full_route.split()[1:-1]
            if RUNWAY_THRESHOLD_IDENT_RE.fullmatch(token)
        ]
        if runway_tokens:
            raise ValueError(
                f"{route_path}:{line_number}: route contains runway threshold "
                f"waypoint(s): {', '.join(runway_tokens)}"
            )
        route_count += 1

    if route_count <= 0:
        raise ValueError(f"{route_path}: no route rows found")

    if not source_airac:
        source_airac = airac

    return {
        "airac": airac,
        "source_airac": source_airac,
        "compatibility_fallback": source_airac < airac,
        "route_count": route_count,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }


def parse_routes_file(root: Path = ROOT) -> dict[str, object]:
    route_path = ROUTES_PATH if root == ROOT else (root / "ROUTES" / "routes.tsv")
    return _parse_routes_tsv(route_path)


def validate_routes_default_file(root: Path = ROOT) -> dict[str, object]:
    route_path = ROUTES_DEFAULT_PATH if root == ROOT else (root / "ROUTES" / "routes_default.tsv")
    if not route_path.exists():
        raise ValueError(f"{route_path}: routes_default.tsv not found")
    result = _parse_routes_tsv(route_path)
    if result["airac"] != BUNDLED_DEFAULT_AIRAC:
        raise ValueError(
            f"{route_path}: expected AIRAC {BUNDLED_DEFAULT_AIRAC} but found {result['airac']}"
        )
    return result


def build_default_routes_manifest(root: Path = ROOT) -> dict[str, object]:
    routes = validate_routes_default_file(root)
    return {
        "schema_version": BUNDLED_DEFAULT_MANIFEST_SCHEMA_VERSION,
        "airac": BUNDLED_DEFAULT_AIRAC,
        "navdata_cycle": BUNDLED_DEFAULT_AIRAC,
        "navdata_revision": "bundled",
        "routes_tier": "offline_fallback",
        "asset_name": "routes_default.tsv",
        "repo_path": "ROUTES/routes_default.tsv",
        "sha256": str(routes["sha256"]),
        "size_bytes": int(routes["size_bytes"]),
        "route_count": int(routes["route_count"]),
    }


def validate_default_routes_manifest(root: Path = ROOT) -> dict[str, object]:
    manifest_path = (
        ROUTES_DEFAULT_MANIFEST_PATH
        if root == ROOT
        else root / "ROUTES" / "routes_default_manifest.json"
    )
    if not manifest_path.exists():
        raise ValueError(f"{manifest_path}: routes_default_manifest.json not found")
    try:
        actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{manifest_path}: invalid JSON: {exc}") from exc
    expected = build_default_routes_manifest(root)
    if actual != expected:
        mismatches = [
            key
            for key in expected
            if actual.get(key) != expected[key]
        ]
        extras = sorted(set(actual) - set(expected))
        fields = ", ".join(sorted(mismatches) + extras)
        raise ValueError(
            f"{manifest_path}: stale default manifest fields: {fields}"
        )
    return expected


def write_default_routes_manifest(root: Path = ROOT) -> Path:
    manifest_path = (
        ROUTES_DEFAULT_MANIFEST_PATH
        if root == ROOT
        else root / "ROUTES" / "routes_default_manifest.json"
    )
    manifest = build_default_routes_manifest(root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


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
        "schema_version": ROUTES_MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag.strip(),
        "commit_sha": commit_sha.strip(),
        "airac": str(routes["airac"]),
        "source_airac": str(routes["source_airac"]),
        "compatibility_fallback": bool(routes["compatibility_fallback"]),
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
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag,
        "release_title": resolved_release_title,
        "commit_sha": str(routes_manifest.get("commit_sha", "")).strip(),
        "published_at": published,
        "assets": {
            "routes_tsv": {
                "repo_path": "ROUTES/routes.tsv",
                "airac": str(routes_manifest.get("airac", "")).strip(),
                "source_airac": str(routes_manifest.get("source_airac", "")).strip(),
                "compatibility_fallback": bool(routes_manifest.get("compatibility_fallback", False)),
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
    parser.add_argument("--write-default", action="store_true", help="Write the deterministic bundled routes_default manifest")
    parser.add_argument("--validate-only", action="store_true", help="Validate ROUTES/routes.tsv without writing manifests")
    parser.add_argument("--validate-default", action="store_true", help="Also validate ROUTES/routes_default.tsv (bundled default AIRAC 2503)")
    parser.add_argument("--release-tag", default="", help="Release tag, for example daily-2026-03-15")
    parser.add_argument("--release-title", default="", help="Release title, for example Daily Community Release - Saturday 2026-03-15")
    parser.add_argument("--asset-name", default="", help="Release asset name, for example routes-2602.tsv")
    parser.add_argument("--download-url", default="", help="Full release asset download URL")
    parser.add_argument("--published-at", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    parser.add_argument("--commit-sha", default="", help="Source commit SHA for the published release")
    args = parser.parse_args()

    try:
        routes = parse_routes_file()
        if args.write_default:
            manifest_path = write_default_routes_manifest()
            print(f"Wrote {manifest_path.relative_to(ROOT).as_posix()}")
            if not args.write:
                return 0
        if args.validate_only and not args.write:
            print(f"Validated routes.tsv: AIRAC {routes['airac']} with {routes['route_count']} rows.")
            if args.validate_default:
                default_routes = validate_default_routes_manifest()
                print(f"Validated routes_default.tsv: AIRAC {default_routes['airac']} with {default_routes['route_count']} rows.")
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
