#!/usr/bin/env python3
"""Validate, deep-check, and aggregate player-contributed route files.

Source of truth: ROUTES/player/<lane>/<PREFIX>/<ORIGIN>_<DEST>.json, written
only by the website contribute flow. This tool never edits those files.

Outputs (release-built):
  - player-routes-<airac>.tsv / player-routes-default-<airac>.tsv overlay
    assets (only rows whose deep-validation status is "ok"),
  - .voiceatc/player_routes_manifest.json (one manifest, two tier objects),
  - .voiceatc/player_routes_status.json (per-route ok/deprecated + reasons;
    the website reads it for badges).

Validation split:
  - Structural rules (JSON schema, caps, DCT bookends, token charset) are the
    website's write contract -> hard errors that fail --validate-only.
  - Navdata-dependent findings (unknown waypoint, broken airway) are
    data-cycle-dependent -> never fail the release; the row is excluded from
    the overlay and marked deprecated with reasons. When graph/navdata inputs
    are unavailable the previous committed status is carried forward
    (fail-open: unknown rows default to "ok").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import routes_connectivity_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATUS_PATH = ROOT / ".voiceatc" / "player_routes_status.json"
REPO_NAME = "lainoa-software/voiceatc-simulator-community"

FILE_SCHEMA_VERSION = 2
MANIFEST_SCHEMA_VERSION = 1
STATUS_SCHEMA_VERSION = 1

LANES = ("current", "default")
MAX_VARIANTS_PER_PAIR = 8
MAX_ROUTE_CHARS = 1000
MAX_ROUTE_TOKENS = 120
MIN_ROUTE_TOKENS = 3
MAX_REASONS_PER_ROUTE = 5
MAX_REASON_CHARS = 160
MAX_REPORTED_FILE_ERRORS = 25

ICAO_RE = re.compile(r"^[A-Z0-9]{4}$")
TOKEN_RE = re.compile(r"^[A-Z0-9]{1,15}$")
ROUTE_ID_RE = re.compile(r"^[0-9a-f]{8}$")
AIRAC_RE = re.compile(r"^[0-9]{4}$")
RUNWAY_TOKEN_RE = re.compile(r"^RW(0[1-9]|[12][0-9]|3[0-6])[LCR]?$")

TSV_COLUMN_HEADER = "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR"

# Deep-validation error codes that exclude a row from the overlay. Warnings
# (dct_unchecked, implicit_direct) and the generator-oriented STAR-entry check
# never deprecate a player route.
DEPRECATING_CODES = frozenset(
    {
        "route_too_short",
        "origin_mismatch",
        "dest_mismatch",
        "route_token_pattern",
        "token_unknown",
        "point_missing",
        "airway_missing",
        "airway_disconnect",
        "airway_to_airport",
        "origin_missing",
        "dest_missing",
    }
)


@dataclass(frozen=True)
class PlayerRoute:
    lane: str
    origin: str
    dest: str
    route_id: str
    route: str
    created_at: str
    creation_airac: str
    repo_path: str
    order_index: int

    @property
    def pair_key(self) -> str:
        return f"{self.origin}_{self.dest}"


def normalize_route(route: str) -> str:
    return " ".join(str(route).upper().split())


def route_id_for(route: str) -> str:
    return hashlib.sha256(normalize_route(route).encode("utf-8")).hexdigest()[:8]


def has_dct_bookends(tokens: list[str]) -> bool:
    if len(tokens) == MIN_ROUTE_TOKENS:
        return tokens[1] == "DCT"
    return (
        len(tokens) >= 5
        and tokens[1] == "DCT"
        and tokens[-2] == "DCT"
        and tokens[2] != "DCT"
        and tokens[-3] != "DCT"
    )


def read_header_airac(path: Path) -> str:
    if not path.is_file():
        return ""
    with path.open("r", encoding="utf-8-sig") as handle:
        header = handle.readline().strip()
    if not header.lower().startswith("airac "):
        return ""
    airac = header[6:].strip()
    return airac if AIRAC_RE.match(airac) else ""


def _validate_route_entry(entry: object, lane: str, origin: str, dest: str, repo_path: str, index: int) -> PlayerRoute:
    if not isinstance(entry, dict):
        raise ValueError(f"{repo_path}: routes[{index}] must be an object")

    route_raw = entry.get("route")
    if not isinstance(route_raw, str) or not route_raw.strip():
        raise ValueError(f"{repo_path}: routes[{index}].route must be a non-empty string")
    route = normalize_route(route_raw)
    if len(route) > MAX_ROUTE_CHARS:
        raise ValueError(f"{repo_path}: routes[{index}].route exceeds {MAX_ROUTE_CHARS} characters")

    tokens = route.split(" ")
    if len(tokens) < MIN_ROUTE_TOKENS:
        raise ValueError(f"{repo_path}: routes[{index}].route needs at least {MIN_ROUTE_TOKENS} tokens")
    if len(tokens) > MAX_ROUTE_TOKENS:
        raise ValueError(f"{repo_path}: routes[{index}].route exceeds {MAX_ROUTE_TOKENS} tokens")
    if tokens[0] != origin:
        raise ValueError(f"{repo_path}: routes[{index}].route must start with origin {origin}")
    if tokens[-1] != dest:
        raise ValueError(f"{repo_path}: routes[{index}].route must end with destination {dest}")
    if not has_dct_bookends(tokens):
        raise ValueError(f"{repo_path}: routes[{index}].route must use DCT bookends")
    for token in tokens:
        if not TOKEN_RE.match(token):
            raise ValueError(f"{repo_path}: routes[{index}].route token '{token}' is not allowed")
    for token in tokens[1:-1]:
        if RUNWAY_TOKEN_RE.match(token):
            raise ValueError(f"{repo_path}: routes[{index}].route contains runway token '{token}'")

    route_id = entry.get("id")
    if not isinstance(route_id, str) or not ROUTE_ID_RE.match(route_id):
        raise ValueError(f"{repo_path}: routes[{index}].id must be 8 lowercase hex characters")
    expected_id = route_id_for(route)
    if route_id != expected_id:
        raise ValueError(f"{repo_path}: routes[{index}].id '{route_id}' does not match route hash '{expected_id}'")

    if "author" in entry:
        raise ValueError(f"{repo_path}: routes[{index}].author is not allowed; player route data is anonymous")

    created_at = entry.get("created_at")
    if not isinstance(created_at, str) or len(created_at.strip()) < 10:
        raise ValueError(f"{repo_path}: routes[{index}].created_at must be an ISO timestamp string")

    creation_airac = entry.get("creation_airac")
    if not isinstance(creation_airac, str) or not AIRAC_RE.match(creation_airac):
        raise ValueError(f"{repo_path}: routes[{index}].creation_airac must be a 4-digit cycle")

    return PlayerRoute(
        lane=lane,
        origin=origin,
        dest=dest,
        route_id=route_id,
        route=route,
        created_at=created_at.strip(),
        creation_airac=creation_airac,
        repo_path=repo_path,
        order_index=index,
    )


def _validate_player_file(path: Path, lane: str, root: Path) -> list[PlayerRoute]:
    repo_path = path.relative_to(root).as_posix()
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{repo_path}: invalid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{repo_path}: player route file must be a JSON object")
    if int(payload.get("schema_version", -1)) != FILE_SCHEMA_VERSION:
        raise ValueError(f"{repo_path}: schema_version must be {FILE_SCHEMA_VERSION}")

    origin = str(payload.get("origin", "")).strip().upper()
    dest = str(payload.get("dest", "")).strip().upper()
    if not ICAO_RE.match(origin):
        raise ValueError(f"{repo_path}: origin '{origin}' is not a 4-character ICAO code")
    if not ICAO_RE.match(dest):
        raise ValueError(f"{repo_path}: dest '{dest}' is not a 4-character ICAO code")
    if origin == dest:
        raise ValueError(f"{repo_path}: origin and dest must differ")

    expected_name = f"{origin}_{dest}.json"
    if path.name != expected_name:
        raise ValueError(f"{repo_path}: filename must be '{expected_name}'")
    expected_prefix = origin[:2]
    if path.parent.name != expected_prefix:
        raise ValueError(f"{repo_path}: parent folder must be origin prefix '{expected_prefix}'")
    if path.parent.parent.name != lane:
        raise ValueError(f"{repo_path}: file must live directly under the '{lane}' lane prefix tree")

    routes_raw = payload.get("routes")
    if not isinstance(routes_raw, list):
        raise ValueError(f"{repo_path}: routes must be an array")
    if len(routes_raw) > MAX_VARIANTS_PER_PAIR:
        raise ValueError(f"{repo_path}: more than {MAX_VARIANTS_PER_PAIR} route variants for one pair")

    routes: list[PlayerRoute] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(routes_raw):
        parsed = _validate_route_entry(entry, lane, origin, dest, repo_path, index)
        if parsed.route_id in seen_ids:
            raise ValueError(f"{repo_path}: duplicate route id '{parsed.route_id}'")
        seen_ids.add(parsed.route_id)
        routes.append(parsed)
    return routes


def _lane_files(lane: str, root: Path) -> list[Path]:
    lane_root = root / "ROUTES" / "player" / lane
    return sorted(lane_root.rglob("*.json")) if lane_root.is_dir() else []


def load_lane(lane: str, root: Path = ROOT) -> list[PlayerRoute]:
    routes: list[PlayerRoute] = []
    for path in _lane_files(lane, root):
        routes.extend(_validate_player_file(path, lane, root))
    routes.sort(key=lambda row: (row.origin, row.dest, row.order_index))
    return routes


def deep_validate_lane(
    rows: list[PlayerRoute],
    graph_db: Path | None,
    navdata_db: Path | None,
) -> dict[str, list[str]] | None:
    """Return {route_id: [reason, ...]} for deprecated rows, or None when the
    deep check could not run (missing/broken navdata input -> carry forward).

    Navdata decides acceptance: the game expands a player route by name against
    tbl_er_enroute_airways. The compacted graph is optional here and only backs
    the FRA DCT warning, which never deprecates a row."""
    if navdata_db is None or not Path(navdata_db).is_file():
        return None
    if not rows:
        return {}

    line_to_route: dict[int, PlayerRoute] = {}
    lines = ["airac 0000", TSV_COLUMN_HEADER]
    for row in rows:
        lines.append(f"{row.origin}\t{row.dest}\t{row.route}\t{row.creation_airac}\t")
        line_to_route[len(lines)] = row

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "player_routes_check.tsv"
            tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            summary = routes_connectivity_check.validate_routes(
                tmp_path,
                Path(graph_db) if graph_db and Path(graph_db).is_file() else None,
                Path(navdata_db),
                strict_dct=False,
                max_findings=1_000_000_000,
            )
    except Exception as exc:
        print(f"player routes deep validation unavailable: {exc}", file=sys.stderr)
        return None

    deprecated: dict[str, list[str]] = {}
    for finding in summary.errors:
        if finding.code not in DEPRECATING_CODES:
            continue
        row = line_to_route.get(finding.line_number)
        if row is None:
            continue
        reasons = deprecated.setdefault(row.route_id, [])
        if len(reasons) >= MAX_REASONS_PER_ROUTE:
            continue
        reason = f"{finding.code}: {finding.detail}"[:MAX_REASON_CHARS]
        if reason not in reasons:
            reasons.append(reason)
    return deprecated


def _previous_lane_status(previous_status: dict[str, object], lane: str) -> dict[str, dict[str, object]]:
    lane_payload = previous_status.get(lane, {})
    if not isinstance(lane_payload, dict):
        return {}
    pairs = lane_payload.get("pairs", {})
    return pairs if isinstance(pairs, dict) else {}


def build_lane_status(
    rows: list[PlayerRoute],
    lane: str,
    lane_airac: str,
    deprecated: dict[str, list[str]] | None,
    previous_status: dict[str, object],
) -> dict[str, object]:
    previous_pairs = _previous_lane_status(previous_status, lane)
    pairs: dict[str, dict[str, object]] = {}
    for row in rows:
        pair_entries = pairs.setdefault(row.pair_key, {})
        if deprecated is None:
            previous_entry = previous_pairs.get(row.pair_key, {})
            entry = previous_entry.get(row.route_id) if isinstance(previous_entry, dict) else None
            if isinstance(entry, dict) and str(entry.get("status", "")) in {"ok", "deprecated"}:
                pair_entries[row.route_id] = {
                    "status": str(entry.get("status")),
                    "checked_airac": str(entry.get("checked_airac", "")),
                    "reasons": [str(reason) for reason in entry.get("reasons", []) if str(reason)][
                        :MAX_REASONS_PER_ROUTE
                    ],
                }
            else:
                pair_entries[row.route_id] = {"status": "ok", "checked_airac": "", "reasons": []}
        else:
            reasons = deprecated.get(row.route_id, [])
            pair_entries[row.route_id] = {
                "status": "deprecated" if reasons else "ok",
                "checked_airac": lane_airac,
                "reasons": reasons,
            }
    return {
        "airac": lane_airac,
        "deep_validation": deprecated is not None,
        "pairs": {key: dict(sorted(value.items())) for key, value in sorted(pairs.items())},
    }


def build_overlay_tsv(rows: list[PlayerRoute], lane_status: dict[str, object], lane_airac: str) -> tuple[str, int]:
    pairs = lane_status.get("pairs", {})
    lines = [f"airac {lane_airac}", TSV_COLUMN_HEADER]
    route_count = 0
    for row in rows:
        entry = pairs.get(row.pair_key, {}).get(row.route_id, {}) if isinstance(pairs, dict) else {}
        if str(entry.get("status", "ok")) != "ok":
            continue
        # Keep the legacy fifth column empty so already-released game builds can
        # parse the overlay without receiving public contributor attribution.
        lines.append(f"{row.origin}\t{row.dest}\t{row.route}\t{row.creation_airac}\t")
        route_count += 1
    return "\n".join(lines) + "\n", route_count


def _download_url(repo: str, release_tag: str, asset_name: str) -> str:
    return f"https://github.com/{repo}/releases/download/{release_tag}/{asset_name}"


def _lane_asset_name(lane: str, lane_airac: str) -> str:
    if lane == "default":
        return f"player-routes-default-{lane_airac}.tsv"
    return f"player-routes-{lane_airac}.tsv"


def load_previous_status(path: Path = STATUS_PATH) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_bundle(
    output_dir: Path,
    release_tag: str,
    published_at: str,
    commit_sha: str,
    download_repo: str,
    graph_dbs: dict[str, Path | None],
    navdata_dbs: dict[str, Path | None],
    root: Path = ROOT,
) -> dict[str, object]:
    lane_airacs = {
        "current": read_header_airac(root / "ROUTES" / "routes.tsv"),
        "default": read_header_airac(root / "ROUTES" / "routes_default.tsv"),
    }
    for lane in LANES:
        if not lane_airacs[lane]:
            raise ValueError(f"unable to read AIRAC header for the '{lane}' lane routes file")

    previous_status = load_previous_status(root / ".voiceatc" / "player_routes_status.json")
    output_dir.mkdir(parents=True, exist_ok=True)

    assets: dict[str, dict[str, object]] = {}
    manifest_tiers: dict[str, dict[str, object]] = {}
    status_payload: dict[str, object] = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "generated_at": published_at,
    }

    for lane in LANES:
        rows = load_lane(lane, root)
        deprecated = deep_validate_lane(rows, graph_dbs.get(lane), navdata_dbs.get(lane))
        lane_status = build_lane_status(rows, lane, lane_airacs[lane], deprecated, previous_status)
        status_payload[lane] = lane_status

        overlay_text, route_count = build_overlay_tsv(rows, lane_status, lane_airacs[lane])
        asset_name = _lane_asset_name(lane, lane_airacs[lane])
        asset_path = output_dir / asset_name
        asset_path.write_text(overlay_text, encoding="utf-8", newline="\n")
        overlay_bytes = asset_path.read_bytes()

        pair_keys = {row.pair_key for row in rows}
        asset_key = "player_routes_tsv" if lane == "current" else "player_routes_default_tsv"
        assets[asset_key] = {
            "asset_name": asset_name,
            "path": str(asset_path),
            "sha256": hashlib.sha256(overlay_bytes).hexdigest(),
            "size_bytes": len(overlay_bytes),
            "route_count": route_count,
            "airac": lane_airacs[lane],
        }
        manifest_tiers[lane] = {
            "airac": lane_airacs[lane],
            "asset_name": asset_name,
            "download_url": _download_url(download_repo, release_tag, asset_name),
            "sha256": assets[asset_key]["sha256"],
            "size_bytes": assets[asset_key]["size_bytes"],
            "route_count": route_count,
            "pair_count": len(pair_keys),
            "content_type": "text/tab-separated-values; charset=utf-8",
        }

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "repo": REPO_NAME,
        "release_tag": release_tag,
        "commit_sha": commit_sha,
        "published_at": published_at,
        "current": manifest_tiers["current"],
        "default": manifest_tiers["default"],
    }
    return {
        "assets": assets,
        "manifests": {
            "player_routes": manifest,
            "player_routes_status": status_payload,
        },
    }


def _format_file_errors(errors: list[str]) -> str:
    lines = [f"{len(errors)} player route file(s) failed validation:"]
    lines.extend(f"  {message}" for message in errors[:MAX_REPORTED_FILE_ERRORS])
    if len(errors) > MAX_REPORTED_FILE_ERRORS:
        lines.append(f"  ... and {len(errors) - MAX_REPORTED_FILE_ERRORS} more")
    return "\n".join(lines)


def validate_tree(root: Path = ROOT) -> dict[str, int]:
    """Validate every player route file and report all faults in one pass.

    Deliberately not `load_lane`, which stops at the first bad file because the
    release build has nothing to do with a partial tree. Here the caller is a
    contributor or the release gate, and one bad batch hiding behind itself
    costs a round trip per file -- the same reason a route is inspected to the
    end rather than stopping at its first bad token."""
    counts: dict[str, int] = {}
    errors: list[str] = []
    for lane in LANES:
        lane_count = 0
        for path in _lane_files(lane, root):
            try:
                lane_count += len(_validate_player_file(path, lane, root))
            except ValueError as exc:
                errors.append(str(exc))
        counts[lane] = lane_count
    if errors:
        raise ValueError(_format_file_errors(errors))

    for committed_path in (root / ".voiceatc" / "player_routes_manifest.json", root / ".voiceatc" / "player_routes_status.json"):
        if not committed_path.is_file():
            continue
        try:
            payload = json.loads(committed_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"{committed_path}: invalid JSON ({exc})") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{committed_path}: must be a JSON object")
    return counts


def write_manifests_from_summary(summary_path: Path, root: Path = ROOT) -> None:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    manifests = payload.get("manifests", {})
    targets = {
        "player_routes": root / ".voiceatc" / "player_routes_manifest.json",
        "player_routes_status": root / ".voiceatc" / "player_routes_status.json",
    }
    for key, target in targets.items():
        manifest = manifests.get(key)
        if not isinstance(manifest, dict):
            raise ValueError(f"{summary_path}: missing '{key}' manifest payload")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"Wrote {target.relative_to(root).as_posix()}")


def _optional_path(value: str) -> Path | None:
    text = value.strip()
    return Path(text) if text else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and aggregate player-contributed community routes.")
    parser.add_argument("--validate-only", action="store_true", help="Validate ROUTES/player trees and committed artifacts")
    parser.add_argument("--build", action="store_true", help="Build overlay TSVs and print the summary JSON")
    parser.add_argument("--write-manifests", action="store_true", help="Write .voiceatc player manifests from --summary")
    parser.add_argument("--summary", default="", help="Path to a summary JSON produced by --build")
    parser.add_argument("--output-dir", default="build/release", help="Directory for built overlay assets")
    parser.add_argument("--release-tag", default="", help="Release tag, for example daily-2026-08-08")
    parser.add_argument("--published-at", default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    parser.add_argument("--commit-sha", default="", help="Source commit SHA for the published release")
    parser.add_argument("--download-repo", default=REPO_NAME, help="owner/repo used for release download URLs")
    parser.add_argument("--current-graph", default="", help="Compacted route graph .s3db for the current lane")
    parser.add_argument("--current-navdata", default="", help="Optional navdata .s3db for the current lane")
    parser.add_argument("--default-graph", default="", help="Compacted route graph .s3db for the default lane")
    parser.add_argument("--default-navdata", default="", help="Optional navdata .s3db for the default lane")
    args = parser.parse_args()

    try:
        if args.write_manifests:
            if not args.summary.strip():
                raise ValueError("--write-manifests requires --summary")
            write_manifests_from_summary(Path(args.summary))
            return 0

        if args.build:
            if not args.release_tag.strip():
                raise ValueError("--build requires --release-tag")
            summary = build_bundle(
                output_dir=Path(args.output_dir),
                release_tag=args.release_tag.strip(),
                published_at=args.published_at.strip(),
                commit_sha=args.commit_sha.strip(),
                download_repo=args.download_repo.strip() or REPO_NAME,
                graph_dbs={"current": _optional_path(args.current_graph), "default": _optional_path(args.default_graph)},
                navdata_dbs={"current": _optional_path(args.current_navdata), "default": _optional_path(args.default_navdata)},
            )
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0

        counts = validate_tree()
        print(
            "Validated player route files: "
            + ", ".join(f"{lane}={counts[lane]} routes" for lane in LANES)
        )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
