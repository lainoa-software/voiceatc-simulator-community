#!/usr/bin/env python3
"""Gated route overlays: validate ``ROUTES/full/*.tsv`` and build the full-feed route tables.

An overlay holds whole replacement rows for origin-destination pairs that already
exist in ``ROUTES/routes.tsv``, for builds that have a capability (for example
``routes.starless_arrivals``: arrivals that end at an approach transition's first fix
when every STAR entry lies behind the aircraft). Every overlay needs a ``routes``
path gate with ``requires`` in ``.voiceatc/gates.json``.

The default feed never changes: ``routes.tsv``, ``routes_legacy.tsv``, their
manifests and the R2 mirror stay byte-identical whether overlays exist or not.
The overlays reach only ``.voiceatc/full/routes_manifest.json``, whose entries are
cumulative variants, most capable first: variant k is the base table with overlays
1..k spliced in (gates.json order) and ``requires`` the union of their capabilities.
A build keeps the first entry it can use and otherwise reads the default manifest.

Overlay format: the same header as ``routes.tsv`` (``airac <cycle>`` then the column
line) and the same five columns. Contracts here carry no version keys.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import release_gates  # noqa: E402
import routes_release_manifest  # noqa: E402


OVERLAY_DIR = Path("ROUTES") / "full"
BASE_PATH = Path("ROUTES") / "routes.tsv"
PROJECTION_ID = "rich_route_coordinates_v1"


class StaleOverlay(ValueError):
    """The overlay was generated for another AIRAC cycle than ``routes.tsv``."""


def overlay_repo_paths(root: Path = ROOT) -> list[str]:
    folder = root / OVERLAY_DIR
    if not folder.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix() for path in folder.glob("*.tsv") if path.is_file())


def _split_table(raw: bytes, label: str) -> tuple[str, str, list[tuple[str, str, str, str]]]:
    """Return (airac, column line, rows) where each row is (origin, dest, text, line ending)."""
    text = raw.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        raise ValueError(f"{label}: needs an 'airac <cycle>' line and a column line")
    first = lines[0].strip()
    if not first.lower().startswith("airac "):
        raise ValueError(f"{label}: first line must be 'airac <cycle>'")
    airac = first[6:].strip()
    columns = lines[1].rstrip("\r\n")
    rows: list[tuple[str, str, str, str]] = []
    for raw_line in lines[2:]:
        body = raw_line.rstrip("\r\n")
        ending = raw_line[len(body):]
        if not body.strip():
            rows.append(("", "", body, ending))
            continue
        parts = body.split("\t")
        rows.append((parts[0].strip().upper(), parts[1].strip().upper() if len(parts) > 1 else "", body, ending))
    return airac, columns, rows


def _overlay_gates(path: str, gates: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        gate
        for gate in gates
        if gate.get("dataset") == "routes" and "path" in gate and fnmatch.fnmatchcase(path, str(gate["path"]))
    ]


def load_overlays(root: Path = ROOT, gates: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    """Validate every overlay against the base table and its gates, in gates.json order.

    Raises ``ValueError`` on any problem; a cycle mismatch raises ``StaleOverlay`` (a
    ``ValueError``) only after every other check on that overlay passed.
    """
    resolved_gates = release_gates.load_gates(root) if gates is None else gates
    base_airac, base_columns, base_rows = _split_table((root / BASE_PATH).read_bytes(), BASE_PATH.as_posix())
    base_width = len(base_columns.split("\t"))
    base_pairs = {(origin, dest) for origin, dest, body, _ in base_rows if body.strip()}
    overlays: list[dict[str, object]] = []
    owner: dict[tuple[str, str], str] = {}
    problems: list[str] = []
    for repo_path in overlay_repo_paths(root):
        matched = _overlay_gates(repo_path, resolved_gates)
        if not matched:
            problems.append(f"{repo_path}: has no routes gate in .voiceatc/gates.json")
            continue
        rule = release_gates._merge_rules(matched)
        if not rule.get("requires"):
            problems.append(f"{repo_path}: its routes gate needs requires")
            continue
        airac, columns, rows = _split_table((root / repo_path).read_bytes(), repo_path)
        if columns != base_columns:
            problems.append(f"{repo_path}: column header {columns!r} differs from {BASE_PATH.as_posix()}")
            continue
        replacements: dict[tuple[str, str], str] = {}
        # A stale overlay (another cycle) fails validate_feed and is skipped at release
        # time, so its rows are not held against this cycle's pairs.
        stale = airac != base_airac
        for line_number, (origin, dest, body, _) in enumerate(rows, start=3):
            if stale or not body.strip():
                continue
            where = f"{repo_path}:{line_number}"
            if len(body.split("\t")) != base_width:
                problems.append(f"{where}: expected {base_width} columns")
                continue
            pair = (origin, dest)
            if pair in replacements:
                problems.append(f"{where}: duplicate pair {origin}-{dest}")
                continue
            if pair not in base_pairs:
                problems.append(f"{where}: {origin}-{dest} is not in {BASE_PATH.as_posix()}")
                continue
            if pair in owner:
                problems.append(f"{where}: {origin}-{dest} is also in {owner[pair]}")
                continue
            replacements[pair] = body
        if not replacements and not stale:
            problems.append(f"{repo_path}: has no route rows")
        for pair in replacements:
            owner.setdefault(pair, repo_path)
        order = min(index for index, gate in enumerate(resolved_gates) if gate in matched)
        overlays.append(
            {
                "id": Path(repo_path).stem,
                "repo_path": repo_path,
                "airac": airac,
                "rule": rule,
                "order": order,
                "replacements": replacements,
                "stale": stale,
            }
        )
    if problems:
        raise ValueError("Route overlays failed validation:\n" + "\n".join(f"- {problem}" for problem in problems))
    overlays.sort(key=lambda overlay: (int(overlay["order"]), str(overlay["repo_path"])))
    return overlays


def splice(base_raw: bytes, replacements: dict[tuple[str, str], str]) -> bytes:
    """Replace whole rows by pair; every other byte (headers, order, line endings) stays."""
    text = base_raw.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    out = lines[:2]
    for raw_line in lines[2:]:
        body = raw_line.rstrip("\r\n")
        parts = body.split("\t")
        pair = (parts[0].strip().upper(), parts[1].strip().upper() if len(parts) > 1 else "")
        replacement = replacements.get(pair)
        out.append(replacement + raw_line[len(body):] if replacement is not None else raw_line)
    bom = b"\xef\xbb\xbf" if base_raw.startswith(b"\xef\xbb\xbf") else b""
    return bom + "".join(out).encode("utf-8")


def build_variants(
    root: Path = ROOT,
    gates: list[dict[str, object]] | None = None,
    *,
    notices: list[str] | None = None,
) -> list[dict[str, object]]:
    """Cumulative variants, most capable first. A stale overlay is skipped with a notice."""
    overlays = load_overlays(root, gates)
    base_airac = _split_table((root / BASE_PATH).read_bytes(), BASE_PATH.as_posix())[0]
    usable: list[dict[str, object]] = []
    for overlay in overlays:
        if overlay["stale"]:
            message = (
                f"{overlay['repo_path']}: airac {overlay['airac']} differs from {BASE_PATH.as_posix()} "
                f"airac {base_airac}; left out of this release"
            )
            if notices is not None:
                notices.append(message)
            print(f"notice: {message}", file=sys.stderr)
            continue
        usable.append(overlay)
    base_raw = (root / BASE_PATH).read_bytes()
    variants: list[dict[str, object]] = []
    replacements: dict[tuple[str, str], str] = {}
    for count, overlay in enumerate(usable, start=1):
        replacements.update(overlay["replacements"])
        rule = release_gates._merge_rules([item["rule"] for item in usable[:count]])
        data = splice(base_raw, replacements)
        variants.append(
            {
                "id": overlay["id"],
                "overlays": [str(item["repo_path"]) for item in usable[:count]],
                "requires": list(rule.get("requires", [])),
                **({"channels": rule["channels"]} if "channels" in rule else {}),
                "data": data,
            }
        )
    variants.reverse()
    for variant in variants:
        parsed = _parse_spliced(variant["data"])
        variant.update(
            {
                "airac": str(parsed["airac"]),
                "source_airac": str(parsed["source_airac"]),
                "route_count": int(parsed["route_count"]),
                "sha256": hashlib.sha256(variant["data"]).hexdigest(),
                "size_bytes": len(variant["data"]),
            }
        )
    return variants


def _parse_spliced(data: bytes) -> dict[str, object]:
    """Run the routes.tsv rules (cycle, CREATION_AIRAC, runway tokens, duplicates) on the result."""
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "routes.tsv"
        scratch.write_bytes(data)
        return routes_release_manifest._parse_routes_tsv(scratch)


def variant_asset_name(airac: str, variant_id: str, most_capable: bool) -> str:
    """``routes-rich-<airac>-full.tsv`` for the most capable variant, ``...-full-<id>.tsv`` otherwise."""
    return f"routes-rich-{airac}-full.tsv" if most_capable else f"routes-rich-{airac}-full-{variant_id}.tsv"


def build_full_routes(
    *,
    root: Path,
    output_dir: Path,
    download_url_for,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Write each variant's rich TSV asset and return (full-manifest entries, assets)."""
    entries: list[dict[str, object]] = []
    assets: list[dict[str, object]] = []
    for index, variant in enumerate(build_variants(root)):
        asset_name = variant_asset_name(str(variant["airac"]), str(variant["id"]), index == 0)
        asset_path = output_dir / asset_name
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(variant["data"])
        entry: dict[str, object] = {
            "id": variant["id"],
            "airac": variant["airac"],
            "source_airac": variant["source_airac"],
            "asset_name": asset_name,
            "download_url": download_url_for(asset_name),
            "sha256": variant["sha256"],
            "size_bytes": variant["size_bytes"],
            "route_count": variant["route_count"],
            "projection_id": PROJECTION_ID,
            "overlays": variant["overlays"],
            "requires": variant["requires"],
        }
        if "channels" in variant:
            entry["channels"] = variant["channels"]
        entries.append(entry)
        assets.append(
            {
                "asset_name": asset_name,
                "path": str(asset_path),
                "sha256": variant["sha256"],
                "size_bytes": variant["size_bytes"],
            }
        )
    return entries, assets


def validate_feed(root: Path = ROOT, *, allow_stale: bool = False) -> list[dict[str, object]]:
    """Everything ``load_overlays`` checks, and the cycle must match.

    With ``allow_stale`` an overlay for another cycle is a notice instead of a failure:
    the release leaves it out (``build_variants``) until it is regenerated. The release
    and the pull-request check both pass it, because an AIRAC rollover changes
    ``routes.tsv`` in one pull request and the overlays only after it (creator decision
    2026-10-09). Without it a hand-made overlay blocks the automated cycle pull request.
    """
    overlays = load_overlays(root)
    stale = [overlay for overlay in overlays if overlay["stale"]]
    # With allow_stale, build_variants below prints the notice for each stale overlay.
    if stale and not allow_stale:
        base_airac = _split_table((root / BASE_PATH).read_bytes(), BASE_PATH.as_posix())[0]
        raise StaleOverlay(
            "Route overlays failed validation:\n"
            + "\n".join(
                f"- {overlay['repo_path']}: airac {overlay['airac']} differs from "
                f"{BASE_PATH.as_posix()} airac {base_airac}"
                for overlay in stale
            )
        )
    build_variants(root)
    return overlays


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the gated route overlays under ROUTES/full/.")
    parser.add_argument("--validate-only", action="store_true", help="Validate overlays and gates (the default action)")
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Report an overlay for another AIRAC cycle as a notice instead of failing",
    )
    args = parser.parse_args()
    try:
        overlays = validate_feed(ROOT, allow_stale=args.allow_stale)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Validated {len(overlays)} route overlay(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
