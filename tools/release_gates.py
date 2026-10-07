#!/usr/bin/env python3
"""Channel gates for community releases.

Content declares what it needs; builds declare what they can do. There are no
version numbers anywhere. The maintainer-edited ``.voiceatc/gates.json`` marks
new content (a file kind, a repo path glob, a route overlay under ``ROUTES/full/``
or a route lane) with ``requires``
(dotted capability names such as ``routes.starless_arrivals``) and/or ``channels``.

The default manifests and zips (the paths every build already reads) keep an
entry only when it has no ``requires`` and its ``channels`` is absent or lists
all three channels: a build that predates the capability system knows no
capability, so anything that requires one stays out of the default feed. The full
manifests under ``.voiceatc/full/`` keep everything plus the gate fields; builds
that read the full feed keep an entry when they have every required capability
and their channel is listed.

Contracts here carry no version keys. A file is identified by its path (and a
full manifest by its ``dataset``); readers ignore keys they do not know, and new
meaning arrives as new optional keys gated with ``requires``.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GATES_PATH = Path(".voiceatc") / "gates.json"
FULL_DIR = Path(".voiceatc") / "full"
CHANNELS = ("stable", "open-beta", "closed-beta")
# Datasets whose default output this producer filters (the release zips).
FILTERED_DATASETS = ("mva", "runway_configs", "sector_data", "misc_drawings", "color_profiles")
# Datasets served by lane (the API worker); a lane gate never touches a default path.
LANE_DATASETS = ("routes", "voice_priors", "snapshots")
# Routes also takes path gates, but only on the gated overlays under ROUTES/full/
# (tools/routes_full_feed.py). The default route tables are never gated.
ROUTES_OVERLAY_PREFIX = "ROUTES/full/"
GATE_SELECTORS = ("kind", "path", "lane")
GATE_RULES = ("requires", "channels")
CAPABILITY_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
CAPABILITY_MAX_LENGTH = 64
KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")
LANE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def validate_capability(name: object, label: str = "capability") -> str:
    """A capability name is lowercase dotted (``routes.starless_arrivals``), at most 64 characters."""
    if not isinstance(name, str) or len(name) > CAPABILITY_MAX_LENGTH or not CAPABILITY_RE.fullmatch(name):
        raise ValueError(
            f"{label}: {name!r} must be a lowercase dotted capability name such as 'routes.starless_arrivals'"
            f" (at most {CAPABILITY_MAX_LENGTH} characters)"
        )
    return name


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc


def validate_gates(payload: object, label: str = str(GATES_PATH)) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label}: must be a JSON object")
    # Tolerant reader: only "gates" is read; other top-level keys are ignored.
    if "gates" not in payload:
        raise ValueError(f"{label}: needs a gates array")
    gates = payload["gates"]
    if not isinstance(gates, list):
        raise ValueError(f"{label}: gates must be an array")
    result: list[dict[str, object]] = []
    for index, gate in enumerate(gates):
        where = f"{label}: gates[{index}]"
        if not isinstance(gate, dict):
            raise ValueError(f"{where} must be an object")
        unknown = set(gate) - {"dataset", *GATE_SELECTORS, *GATE_RULES}
        if unknown:
            raise ValueError(f"{where} has unknown keys {sorted(unknown)}")
        dataset = gate.get("dataset")
        selectors = [key for key in GATE_SELECTORS if key in gate]
        if len(selectors) != 1:
            raise ValueError(f"{where} needs exactly one of kind, path or lane")
        selector = selectors[0]
        if selector == "lane":
            if dataset not in LANE_DATASETS:
                raise ValueError(f"{where}: lane gates apply to {', '.join(LANE_DATASETS)}")
            if not isinstance(gate["lane"], str) or not LANE_RE.fullmatch(gate["lane"]):
                raise ValueError(f"{where}: lane must be a lowercase name")
        elif dataset == "routes":
            value = gate[selector]
            if selector != "path":
                raise ValueError(f"{where}: routes takes a path gate (an overlay under {ROUTES_OVERLAY_PREFIX}) or a lane gate")
            if not isinstance(value, str) or not value.startswith(ROUTES_OVERLAY_PREFIX) or ".." in value:
                raise ValueError(f"{where}: a routes path gate selects an overlay under {ROUTES_OVERLAY_PREFIX}")
            if "requires" not in gate:
                raise ValueError(f"{where}: a routes overlay gate needs requires")
        else:
            if dataset not in FILTERED_DATASETS:
                raise ValueError(f"{where}: dataset must be one of {', '.join(FILTERED_DATASETS)}")
            value = gate[selector]
            if selector == "kind" and (not isinstance(value, str) or not KIND_RE.fullmatch(value)):
                raise ValueError(f"{where}: kind must be a lowercase file kind such as 'style'")
            if selector == "path":
                if not isinstance(value, str) or not value.strip() or value.startswith("/") or ".." in value:
                    raise ValueError(f"{where}: path must be a repo-relative path or glob")
        if not any(key in gate for key in GATE_RULES):
            raise ValueError(f"{where} needs requires and/or channels")
        if "requires" in gate:
            requires = gate["requires"]
            if not isinstance(requires, list) or not requires:
                raise ValueError(f"{where}: requires must be a non-empty array of capability names")
            for name in requires:
                validate_capability(name, f"{where}: requires")
            if len(set(requires)) != len(requires):
                raise ValueError(f"{where}: duplicate capability in requires")
        if "channels" in gate:
            channels = gate["channels"]
            if not isinstance(channels, list) or not channels:
                raise ValueError(f"{where}: channels must be a non-empty array")
            for channel in channels:
                if channel not in CHANNELS:
                    raise ValueError(f"{where}: unknown channel {channel!r}")
            if len(set(channels)) != len(channels):
                raise ValueError(f"{where}: duplicate channel")
        result.append(dict(gate))
    return result


def load_gates(root: Path = ROOT) -> list[dict[str, object]]:
    path = root / GATES_PATH
    if not path.is_file():
        return []
    return validate_gates(_read_json(path), str(path))


def is_default_visible(rule: dict[str, object]) -> bool:
    """True when a build that knows no capabilities, on any channel, keeps this entry.

    Old builds know no capabilities, so any ``requires`` keeps the entry out of the
    default feed. A ``channels`` list keeps it only when it names all three channels.
    """
    if rule.get("requires"):
        return False
    channels = rule.get("channels")
    if isinstance(channels, list) and any(channel not in channels for channel in CHANNELS):
        return False
    return True


def _merge_rules(gates: list[dict[str, object]]) -> dict[str, object]:
    """Several gates on one item: every required capability and the common channels."""
    merged: dict[str, object] = {}
    for gate in gates:
        if "requires" in gate:
            current_requires = list(merged.get("requires", []))
            merged["requires"] = current_requires + [
                name for name in gate["requires"] if name not in current_requires
            ]
        if "channels" in gate:
            current_channels = merged.get("channels")
            allowed = list(gate["channels"])
            if isinstance(current_channels, list):
                allowed = [channel for channel in current_channels if channel in allowed]
            merged["channels"] = [channel for channel in CHANNELS if channel in allowed]
    return merged


def _matching_gates(
    gates: list[dict[str, object]],
    *,
    kind: str | None,
    paths: list[str],
) -> list[dict[str, object]]:
    matched: list[dict[str, object]] = []
    for gate in gates:
        if "kind" in gate and kind is not None and gate["kind"] == kind:
            matched.append(gate)
        elif "path" in gate and any(fnmatch.fnmatchcase(path, str(gate["path"])) for path in paths):
            matched.append(gate)
    return matched


def apply_gates(
    dataset: str,
    entries: dict[str, object],
    *,
    gates: list[dict[str, object]],
    archive_sources: dict[str, str] | None = None,
    required_kinds: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Split one dataset's entries into the default view and the annotated full-feed list.

    ``entries`` is the manifest's entry map (airports, bundles or profiles). An
    entry is either one file (``repo_path``) or a ``files`` map by kind. A gated
    file whose rule is not default-visible leaves the default entry; when that
    removes a required kind (``required_kinds``; ``None`` means every kind the
    entry has) or the last file, the whole entry leaves. Ungated data returns
    ``default`` equal to ``entries`` (same objects, same order).
    """
    dataset_gates = [gate for gate in gates if gate.get("dataset") == dataset and "lane" not in gate]
    sources = archive_sources or {}
    default: dict[str, object] = {}
    full_entries: list[dict[str, object]] = []
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{dataset}: entry '{key}' must be an object")
        full_entry: dict[str, object] = {"id": key}
        files = entry.get("files")
        if isinstance(files, dict):
            kept_files: dict[str, object] = {}
            full_files: dict[str, object] = {}
            dropped_kinds: list[str] = []
            for kind, file_entry in files.items():
                repo_path = str(file_entry.get("repo_path", "")) if isinstance(file_entry, dict) else ""
                paths = [repo_path, sources.get(repo_path, repo_path)]
                rule = _merge_rules(_matching_gates(dataset_gates, kind=kind, paths=paths))
                full_files[kind] = {**file_entry, **rule} if rule else file_entry
                if rule and not is_default_visible(rule):
                    dropped_kinds.append(kind)
                else:
                    kept_files[kind] = file_entry
            required = tuple(files) if required_kinds is None else required_kinds
            entry_survives = bool(kept_files) and not any(kind in required for kind in dropped_kinds)
            if entry_survives:
                default[key] = entry if not dropped_kinds else {**entry, "files": kept_files}
            full_entry.update({**entry, "files": full_files})
        else:
            repo_path = str(entry.get("repo_path", ""))
            paths = [repo_path, sources.get(repo_path, repo_path)]
            rule = _merge_rules(_matching_gates(dataset_gates, kind=None, paths=paths))
            if not rule or is_default_visible(rule):
                default[key] = entry
            full_entry.update({**entry, **rule})
        full_entries.append(full_entry)
    return {"default": default, "full_entries": full_entries}


def entry_repo_paths(entries: dict[str, object]) -> list[str]:
    paths: set[str] = set()
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        files = entry.get("files")
        if isinstance(files, dict):
            paths.update(str(item["repo_path"]) for item in files.values() if isinstance(item, dict))
        elif "repo_path" in entry:
            paths.add(str(entry["repo_path"]))
    return sorted(paths)


def build_full_manifest(
    *,
    dataset: str,
    full_entries: list[dict[str, object]],
    repo: str,
    release_tag: str,
    commit_sha: str,
    published_at: str,
    asset: dict[str, object] | None,
    download_url: str = "",
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "dataset": dataset,
        "repo": repo,
        "release_tag": release_tag.strip(),
        "commit_sha": commit_sha.strip(),
        "published_at": published_at.strip(),
        "generated_at": published_at.strip(),
        "entry_count": len(full_entries),
        "entries": full_entries,
    }
    if asset is not None:
        manifest["asset_name"] = str(asset["asset_name"])
        manifest["download_url"] = download_url
        manifest["sha256"] = str(asset["sha256"])
        manifest["size_bytes"] = int(asset["size_bytes"])
    return manifest


def full_manifest_path(dataset: str, root: Path = ROOT) -> Path:
    return root / FULL_DIR / f"{dataset}_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate .voiceatc/gates.json.")
    parser.add_argument("--validate-only", action="store_true", help="Validate the gates file (the default action)")
    parser.parse_args()
    try:
        gates = load_gates(ROOT)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Validated {len(gates)} gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
