"""Shared default plus complete Bundled/Latest aviation documents."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

TIERS = ("bundled", "latest")
CAPABILITY = "community.airac_overrides"
IDENTITY_KEYS = ("airport", "airports", "scope", "scope_id")


def documents(payload: dict) -> list[tuple[str, dict]]:
    if not isinstance(payload, dict):
        raise ValueError("aviation document must be an object")
    default = {key: value for key, value in payload.items() if key != "airac_overrides"}
    overrides = payload.get("airac_overrides", {})
    if not isinstance(overrides, dict) or any(key not in TIERS for key in overrides):
        raise ValueError("airac_overrides must be an object with only bundled and latest keys")
    result = [("", default)]
    for tier, document in overrides.items():
        if not isinstance(document, dict):
            raise ValueError(f"{tier} override must be a complete document object")
        if "airac_overrides" in document:
            raise ValueError("nested airac_overrides are prohibited")
        if any(document.get(key) != default.get(key) for key in IDENTITY_KEYS):
            raise ValueError(f"{tier} override must preserve document identity")
        result.append((tier, document))
    return result


def resolve(payload: dict, tier: str) -> dict:
    variants = dict(documents(payload))
    return deepcopy(variants.get(tier, variants[""]))


def validate_references(payload: dict, path: Path) -> None:
    """Check available runway-config authorities in the same airport/scope, per tier."""
    if path.name == "runway_configs.json" or not isinstance(payload, dict):
        return
    airports = payload.get("airports", [payload.get("airport", path.parent.name)])
    if isinstance(airports, str):
        airports = [airports]
    candidates = [path.with_name("runway_configs.json")]
    candidates += [path.parent / str(airport) / "runway_configs.json" for airport in airports]
    if path.name.startswith("sector_"):
        candidates += list(path.parent.glob("*/runway_configs.json"))
    runway_documents = [json.loads(item.read_text(encoding="utf-8")) for item in dict.fromkeys(candidates) if item.is_file()]
    if not runway_documents or not any("airac_overrides" in item for item in [payload, *runway_documents]):
        return
    for tier in ("", *TIERS):
        ids = {str(row["id"]).upper() for item in runway_documents
               for row in resolve(item, tier).get("runway_configs", resolve(item, tier).get("runway_configurations", []))}
        unknown = _configuration_refs(resolve(payload, tier), path.name.startswith("sector_")) - ids
        if unknown:
            raise ValueError(f"{path}: {tier} references unknown runway configurations: {', '.join(sorted(unknown))}")


def _configuration_refs(value: object, sector: bool) -> set[str]:
    found: set[str] = set()
    if isinstance(value, list):
        for item in value:
            found.update(_configuration_refs(item, sector))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "configs" and isinstance(item, dict):
                found.update(str(identifier).upper() for identifier in item)
            elif key == "configs" or (sector and key in {"runway_configs", "runway_configurations", "runways"}):
                tokens = re.split(r"[,;|+\t ]+", item) if isinstance(item, str) else item
                if isinstance(tokens, list):
                    found.update(token.upper() for token in tokens if isinstance(token, str) and token)
            found.update(_configuration_refs(item, sector))
    return found


def full_repo_paths(gated: dict) -> list[str]:
    paths = set()
    for entry in gated["full_entries"]:
        for item in entry.get("files", {"content": entry}).values():
            paths.add(item["repo_path"])
    return sorted(paths)


def default_entry(root: Path, entry: dict) -> dict:
    """Materialize legacy bytes separately, never overwrite a contributor's file."""
    result = deepcopy(entry)
    if "files" in result:
        result["files"] = {kind: default_entry(root, item) for kind, item in result["files"].items()}
        return result
    source = root / result["repo_path"]
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "airac_overrides" not in payload:
        return result
    raw = (json.dumps(resolve(payload, ""), indent=2) + "\n").encode("utf-8")
    target = Path(".voiceatc/defaults") / result["repo_path"]
    (root / target).parent.mkdir(parents=True, exist_ok=True)
    (root / target).write_bytes(raw)
    if source.name.startswith("visual_"):
        for sibling in source.parent.glob("visual_*.json"):
            if sibling == source:
                continue
            sibling_payload = json.loads(sibling.read_text(encoding="utf-8"))
            (root / target.parent / sibling.name).write_text(
                json.dumps(resolve(sibling_payload, ""), indent=2) + "\n", encoding="utf-8")
    result.update(repo_path=target.as_posix(), sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    return result


def project_feed(root: Path, gated: dict) -> None:
    """Old full-feed readers select the default; capable readers select the last entry."""
    gated["default"] = {key: default_entry(root, item) for key, item in gated["default"].items()}
    entries = []
    for entry in gated["full_entries"]:
        legacy = default_entry(root, entry)
        if legacy != entry:
            entries.append(legacy)
            entry = {**entry, "requires": sorted(set(entry.get("requires", [])) | {CAPABILITY})}
        entries.append(entry)
    gated["full_entries"] = entries


def publish_raw_manifest(root: Path, manifest_path: Path, manifest: dict) -> dict:
    full_path = root / ".voiceatc/full" / manifest_path.name
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(json.dumps({**manifest, "requires": [CAPABILITY]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**manifest, "airports": {key: default_entry(root, entry) for key, entry in manifest["airports"].items()}}


def project_sector_feed(root: Path, gated: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Legacy sectors require scope-relative paths; full variants use gated aliases."""
    default_sources: dict[str, str] = {}
    full_sources: dict[str, str] = {}

    def project(entry: dict, sources: dict[str, str]) -> dict:
        legacy = default_entry(root, entry)
        for kind, item in legacy["files"].items():
            original_path = entry["files"][kind]["repo_path"]
            sources[original_path] = item["repo_path"]
            item["repo_path"] = original_path
        return legacy

    gated["default"] = {key: project(item, default_sources) for key, item in gated["default"].items()}
    entries = []
    for entry in gated["full_entries"]:
        legacy = project(entry, full_sources)
        if legacy != entry:
            entries.append(legacy)
            entry = deepcopy(entry)
            entry["requires"] = sorted(set(entry.get("requires", [])) | {CAPABILITY})
            for item in entry["files"].values():
                source = item["repo_path"]
                alias = "airac_variants/" + source
                full_sources[alias] = source
                item["repo_path"] = alias
        entries.append(entry)
    gated["full_entries"] = entries
    return default_sources, full_sources
