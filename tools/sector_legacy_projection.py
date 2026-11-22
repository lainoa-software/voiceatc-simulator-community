#!/usr/bin/env python3
"""Project schema-2 sector bundles back into legacy files for default and tma_file feeds.

Default (legacy) builds read ``sector_configs.json`` and ``sector_influence.json``
at each terminal bundle path, and ``community.tma_file`` builds read schema-1
``tma.json`` from the full feed. Neither exists in schema-2 source.

``release/legacy_frozen/`` holds the verbatim legacy bytes captured from ``main``
before the schema-2 layout conversion for every bundle that published them, plus
``release/legacy_frozen/index.json`` recording each bundle's schema-2 source
hashes. When a bundle's current schema-2 source files match the index, publish
ships the frozen bytes verbatim; edited or new bundles fall back to generating
legacy files from schema 2.
"""
from __future__ import annotations

try:
    from . import airac_overrides
except ImportError:  # run as a script, or loaded by file path (tests)
    import sys
    from pathlib import Path

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import airac_overrides

import argparse
from copy import deepcopy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FROZEN_DIR = Path("release") / "legacy_frozen"
FROZEN_INDEX_PATH = FROZEN_DIR / "index.json"
TMA_FILE_CAPABILITY = "community.tma_file"
AIRSPACE_FILES_CAPABILITY = "community.airspace_files"


def load_frozen_index(root: Path) -> dict[str, dict[str, object]]:
    index_path = root / FROZEN_INDEX_PATH
    if not index_path.is_file():
        return {}
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    bundles = payload.get("bundles", {})
    return bundles if isinstance(bundles, dict) else {}


def load_frozen_files_index(root: Path) -> dict[str, dict[str, object]]:
    """Return per-file frozen snapshot metadata keyed by repo_path."""
    index_path = root / FROZEN_INDEX_PATH
    if not index_path.is_file():
        return {}
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    files = payload.get("files", {})
    return files if isinstance(files, dict) else {}
    if not isinstance(bundles, dict):
        return {}
    return {
        str(k).strip().replace("\\", "/"): v
        for k, v in bundles.items()
        if isinstance(v, dict)
    }


def _find_ancestor_acc_structure(root: Path, bundle_path: str) -> Path | None:
    cur = (root / bundle_path).parent
    while cur != root and cur.parent != cur:
        acc_path = cur / "acc_structure.json"
        if acc_path.is_file():
            return acc_path
        cur = cur.parent
    return None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(_canonical_lf(path.read_bytes())).hexdigest()


def bundle_source_hashes(
    root: Path,
    bundle_path: str,
    src_files: dict[str, object],
) -> dict[str, str]:
    """SHA-256 hashes of a terminal bundle's schema-2 source files and ancestor acc_structure."""
    hashes: dict[str, str] = {}
    for kind, fname in (
        ("tma_structure", "tma_structure.json"),
        ("definitions", "sector_definitions.json"),
        ("tma_coordination", "tma_coordination.json"),
    ):
        entry = src_files.get(kind)
        if isinstance(entry, dict) and entry.get("repo_path"):
            hashes[fname] = _sha256_file(root / str(entry["repo_path"]))
    acc_path = _find_ancestor_acc_structure(root, bundle_path)
    if acc_path is not None:
        hashes["acc_structure.json"] = _sha256_file(acc_path)
    return dict(sorted(hashes.items()))


def _resolve_default_doc(document: dict) -> dict:
    if "airac_overrides" in document:
        return airac_overrides.resolve(document, "")
    return document


def _derive_served_airports(tma_structure: dict) -> list[str]:
    airports: list[str] = []
    for layout in tma_structure.get("layouts", []):
        if not isinstance(layout, dict):
            continue
        for airport in layout.get("airports", []):
            code = str(airport).strip().upper()
            if code and code not in airports:
                airports.append(code)
    for unit in tma_structure.get("units", []):
        if not isinstance(unit, dict):
            continue
        services = unit.get("services", [])
        if isinstance(services, list) and "tower" in services and "airport" in unit:
            code = str(unit["airport"]).strip().upper()
            if code and code not in airports:
                airports.append(code)
    return airports


def project_configs_and_influence(
    tma_structure: dict,
    *,
    sector_aliases: dict[str, list[str]] | None = None,
    configs_airport: str | None = None,
    influence_airport: str | None = None,
    auto_airport_for_non_prefixed: bool = False,
) -> tuple[dict, dict]:
    """Generate (sector_configs_payload, sector_influence_payload) from schema-2 tma_structure."""
    tma_doc = _resolve_default_doc(tma_structure)
    aliases = {
        str(k).strip().upper(): [str(item).strip().upper() for item in v if str(item).strip()]
        for k, v in (sector_aliases or {}).items()
        if isinstance(v, list)
    }

    sector_configs: list[dict] = []
    influence_order: list[str] = []
    influence_airports: dict[str, list[str]] = {}

    for layout in tma_doc.get("layouts", []):
        if not isinstance(layout, dict):
            continue
        config_id = str(layout.get("id", "")).strip().upper()
        runways_obj = layout.get("runways")
        runway_configs: list[str] = []
        if isinstance(runways_obj, dict) and runways_obj:
            seen_rwy: set[str] = set()
            for _apt, presets in runways_obj.items():
                if isinstance(presets, list):
                    for preset in presets:
                        token = str(preset).strip()
                        if token and token not in seen_rwy:
                            seen_rwy.add(token)
                            runway_configs.append(token)

        layout_airports = [
            str(airport).strip().upper()
            for airport in layout.get("airports", [])
            if str(airport).strip()
        ]
        sectors_out: list[dict] = []
        for pos_idx, pos in enumerate(layout.get("positions", [])):
            if not isinstance(pos, dict):
                continue
            raw_sector = str(pos.get("sector", "")).strip().upper()
            if raw_sector in aliases and aliases[raw_sector]:
                parts = list(aliases[raw_sector])
            else:
                parts = [part.strip() for part in raw_sector.split("~") if part.strip()]
            if not parts:
                continue
            has_delim = any(ch in parts[0] for ch in (" ", "\t", ",", ";", "|", "+"))
            entry: dict[str, object] = (
                {"sector_id": parts[0]} if len(parts) == 1 and not has_delim else {"sector_ids": parts}
            )
            freq = str(pos.get("frequency", "")).strip()
            if freq:
                entry["frequency"] = freq
            sectors_out.append(entry)

            pos_airports = layout_airports if pos_idx == 0 else []
            for sid in parts:
                if sid not in influence_airports:
                    influence_order.append(sid)
                    influence_airports[sid] = []
                for airport in pos_airports:
                    if airport not in influence_airports[sid]:
                        influence_airports[sid].append(airport)

        row: dict[str, object] = {"sector_config_id": config_id}
        if runway_configs:
            row["runway_configs"] = runway_configs
        row["sectors"] = sectors_out
        sector_configs.append(row)

    sector_influences = [
        {"sector_id": sid, "airports": sorted(influence_airports[sid])}
        for sid in influence_order
        if influence_airports[sid]
    ]

    served_airports = _derive_served_airports(tma_doc)
    cfg_payload: dict[str, object] = {}
    resolved_cfg_apt = (configs_airport or "").strip().upper()
    if resolved_cfg_apt and (not served_airports or resolved_cfg_apt in served_airports):
        cfg_payload["airport"] = resolved_cfg_apt
    elif (
        auto_airport_for_non_prefixed
        and len(served_airports) == 1
        and not any(sid.startswith(served_airports[0]) for sid in influence_order)
    ):
        cfg_payload["airport"] = served_airports[0]
    cfg_payload["sector_configs"] = sector_configs

    inf_payload: dict[str, object] = {}
    resolved_inf_apt = (influence_airport or "").strip().upper()
    if resolved_inf_apt and (not served_airports or resolved_inf_apt in served_airports):
        inf_payload["airport"] = resolved_inf_apt
    inf_payload["sector_influences"] = sector_influences

    return cfg_payload, inf_payload


def _derive_tma_name(bundle_key: str) -> str:
    if bundle_key.endswith("_TMA"):
        return f"{bundle_key[:-4].replace('_', ' ').title()} TMA"
    return bundle_key.replace("_", " ").title()


def _referenced_unit_ids(tma_structure: dict, tma_coordination: dict | None) -> set[str]:
    needed: set[str] = set()
    for layout in tma_structure.get("layouts", []):
        if not isinstance(layout, dict):
            continue
        for pos in layout.get("positions", []):
            if isinstance(pos, dict) and pos.get("unit"):
                needed.add(str(pos["unit"]).strip())
        for duty in layout.get("on_duty", []):
            if isinstance(duty, dict) and duty.get("unit"):
                needed.add(str(duty["unit"]).strip())
    if isinstance(tma_coordination, dict):
        for agr in tma_coordination.get("agreements", []):
            if not isinstance(agr, dict):
                continue
            for key in ("from", "to"):
                if agr.get(key):
                    needed.add(str(agr[key]).strip())
            go_around = agr.get("go_around")
            if isinstance(go_around, dict) and go_around.get("to"):
                needed.add(str(go_around["to"]).strip())
    return {uid for uid in needed if uid}


def _safe_unit_aliases(
    units: list[dict],
    referenced: set[str],
    raw_aliases: dict[str, str] | None,
) -> dict[str, str]:
    if not raw_aliases:
        return {}
    present_ids = {str(u.get("id", "")).strip() for u in units if u.get("id")} | referenced
    candidate = {
        str(k).strip(): str(v).strip()
        for k, v in raw_aliases.items()
        if str(k).strip() and str(v).strip()
    }
    mapped_targets: dict[str, str] = {}
    safe: dict[str, str] = {}
    for uid in sorted(present_ids):
        target = candidate.get(uid, uid)
        if target in mapped_targets and mapped_targets[target] != uid:
            return {}
        mapped_targets[target] = uid
        if target != uid:
            safe[uid] = target
    return safe


def project_schema1_tma(
    tma_structure: dict,
    tma_coordination: dict | None,
    acc_units_by_id: dict[str, dict],
    bundle_key: str,
    *,
    unit_aliases: dict[str, str] | None = None,
    tma_name: str | None = None,
) -> dict:
    """Reconstruct a schema-1 tma.json payload from schema-2 files and ACC center units."""
    tma_doc = _resolve_default_doc(tma_structure)
    units = [deepcopy(unit) for unit in tma_doc.get("units", []) if isinstance(unit, dict)]
    present_ids = {str(unit.get("id", "")).strip() for unit in units}
    referenced = _referenced_unit_ids(tma_doc, tma_coordination)
    for uid in sorted(referenced):
        if uid not in present_ids and uid in acc_units_by_id:
            units.append(deepcopy(acc_units_by_id[uid]))
            present_ids.add(uid)

    aliases = _safe_unit_aliases(units, referenced, unit_aliases)
    for unit in units:
        uid = str(unit.get("id", "")).strip()
        if uid in aliases:
            unit["id"] = aliases[uid]

    layouts = deepcopy(tma_doc.get("layouts", []))
    for layout in layouts:
        if not isinstance(layout, dict):
            continue
        layout_airports = [
            str(airport).strip().upper()
            for airport in layout.pop("airports", [])
            if str(airport).strip()
        ]
        positions = layout.get("positions", [])
        if isinstance(positions, list) and positions and isinstance(positions[0], dict) and layout_airports:
            positions[0]["airports"] = layout_airports
        for pos in positions:
            if isinstance(pos, dict) and pos.get("unit"):
                uid = str(pos["unit"]).strip()
                if uid in aliases:
                    pos["unit"] = aliases[uid]
        for duty in layout.get("on_duty", []):
            if isinstance(duty, dict) and duty.get("unit"):
                uid = str(duty["unit"]).strip()
                if uid in aliases:
                    duty["unit"] = aliases[uid]

    resolved_name = (tma_name or "").strip() or _derive_tma_name(bundle_key)
    out: dict[str, object] = {
        "schema": 1,
        "tma": {"id": bundle_key, "name": resolved_name},
        "airports": _derive_served_airports(tma_doc),
        "units": units,
    }
    if "zones" in tma_doc:
        out["zones"] = deepcopy(tma_doc["zones"])
    out["layouts"] = layouts
    if "configurations" in tma_doc:
        out["configurations"] = deepcopy(tma_doc["configurations"])
    if isinstance(tma_coordination, dict) and tma_coordination.get("agreements"):
        agreements_out: list[dict] = []
        for agr in tma_coordination["agreements"]:
            if not isinstance(agr, dict):
                continue
            row = deepcopy(agr)
            for key in ("from", "to"):
                if row.get(key):
                    uid = str(row[key]).strip()
                    if uid in aliases:
                        row[key] = aliases[uid]
            go_around = row.get("go_around")
            if isinstance(go_around, dict) and go_around.get("to"):
                uid = str(go_around["to"]).strip()
                if uid in aliases:
                    go_around["to"] = aliases[uid]
            fix = row.get("fix")
            if isinstance(fix, list) and len(fix) == 1:
                row["fix"] = fix[0]
            agreements_out.append(row)
        out["agreements"] = agreements_out
    return out


def _collect_acc_units_for_bundle(root: Path, bundle_path: str, all_acc_units: dict[str, dict]) -> dict[str, dict]:
    merged = dict(all_acc_units)
    acc_path = _find_ancestor_acc_structure(root, bundle_path)
    if acc_path is not None:
        payload = json.loads(acc_path.read_text(encoding="utf-8"))
        for unit in payload.get("units", []):
            if isinstance(unit, dict) and unit.get("id"):
                merged[str(unit["id"]).strip()] = unit
    return merged


def _file_entry(repo_path: str, raw_bytes: bytes, *, requires: list[str] | None = None) -> dict[str, object]:
    entry: dict[str, object] = {
        "repo_path": repo_path,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }
    if requires is not None:
        entry["requires"] = requires
    return entry


def _frozen_files_if_fresh(
    root: Path,
    bundle_path: str,
    src_files: dict[str, object],
    index_entry: dict[str, object] | None,
) -> dict[str, bytes] | None:
    if not isinstance(index_entry, dict):
        return None
    expected_hashes = index_entry.get("source_sha256")
    if not isinstance(expected_hashes, dict):
        return None
    current_hashes = bundle_source_hashes(root, bundle_path, src_files)
    if current_hashes != expected_hashes:
        return None

    frozen_list = index_entry.get("frozen_files")
    if not isinstance(frozen_list, list):
        return None
    frozen_set = {str(name) for name in frozen_list}
    required = {"sector_configs.json", "sector_influence.json", "sector_definitions.json"}
    if "tma_coordination" in src_files:
        required.add("tma.json")
    if not required <= frozen_set:
        return None

    frozen_dir = root / FROZEN_DIR / bundle_path
    loaded: dict[str, bytes] = {}
    for fname in sorted(frozen_set):
        fpath = frozen_dir / fname
        if not fpath.is_file():
            return None
        loaded[fname] = fpath.read_bytes()
    return loaded


def _canonical_lf(raw_bytes: bytes) -> bytes:
    return raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _tma_position_ids(tma_structure: dict[str, object]) -> list[str]:
    pos_ids: list[str] = []
    for layout in tma_structure.get("layouts", []) or []:  # type: ignore[union-attr]
        if not isinstance(layout, dict):
            continue
        for pos in layout.get("positions", []) or []:
            if isinstance(pos, dict) and pos.get("sector"):
                sid = str(pos["sector"]).strip()
                if sid and sid not in pos_ids:
                    pos_ids.append(sid)
    return pos_ids


def _pick_legacy_sector_id(
    refs: list[str],
    all_pos_ids: list[str],
    aliases: dict[str, list[str]],
    used_counts: dict[tuple[str, ...], int],
) -> str:
    clean_refs = [r for r in refs if r]
    if not clean_refs:
        return ""
    expand = lambda sid: [str(x).strip() for x in aliases.get(sid, [sid]) if str(x).strip()]
    ordered_first = expand(clean_refs[0])
    inter_sets = [set(expand(r)) for r in clean_refs]
    inter = set.intersection(*inter_sets) if inter_sets else set()
    excluded: set[str] = set()
    ref_set = set(clean_refs)
    for pid in all_pos_ids:
        if pid not in ref_set:
            excluded.update(expand(pid))
    exact_set = inter - excluded
    candidates = [c for c in ordered_first if c in exact_set]
    for c in sorted(exact_set):
        if c not in candidates:
            candidates.append(c)
    if not candidates:
        candidates = [c for c in ordered_first if c in inter]
        for c in sorted(inter):
            if c not in candidates:
                candidates.append(c)
    if not candidates:
        candidates = ordered_first or [clean_refs[0]]
    key = tuple(candidates)
    idx = used_counts.get(key, 0)
    used_counts[key] = idx + 1
    return candidates[idx % len(candidates)]


def _convert_definitions_doc(
    doc: dict[str, object],
    all_pos_ids: list[str],
    aliases: dict[str, list[str]],
) -> dict[str, object]:
    out = deepcopy(doc)
    raw_rows = out.get("sector_definitions")
    if isinstance(raw_rows, list):
        used_counts: dict[tuple[str, ...], int] = {}
        new_rows: list[object] = []
        for row in raw_rows:
            if not isinstance(row, dict):
                new_rows.append(row)
                continue
            item: dict[str, object] = {}
            raw_ids = row.get("sector_ids")
            if isinstance(raw_ids, list):
                refs = [str(x).strip() for x in raw_ids if str(x).strip()]
            else:
                refs = [str(row.get("sector_id", "")).strip()]
            sector_id = _pick_legacy_sector_id(refs, all_pos_ids, aliases, used_counts)
            for k, v in row.items():
                if k in ("sector_ids", "sector_id"):
                    if "sector_id" not in item:
                        item["sector_id"] = sector_id
                elif k == "is_delegation":
                    if "delegation" not in row:
                        item["delegation"] = bool(v)
                else:
                    item[k] = v
            if "sector_id" not in item:
                item["sector_id"] = sector_id
            new_rows.append(item)
        out["sector_definitions"] = new_rows
    if isinstance(out.get("airac_overrides"), dict):
        overrides: dict[str, object] = {}
        for tier, tier_doc in out["airac_overrides"].items():  # type: ignore[union-attr]
            if isinstance(tier_doc, dict):
                overrides[tier] = _convert_definitions_doc(tier_doc, all_pos_ids, aliases)
            else:
                overrides[tier] = tier_doc
        out["airac_overrides"] = overrides
    return out


def project_sector_definitions(
    definitions_doc: dict[str, object],
    tma_structure: dict[str, object],
    *,
    sector_aliases: dict[str, list[str]] | None = None,
) -> bytes:
    """Project schema-2 sector_definitions.json back to scalar legacy sector_id rows."""
    all_pos_ids = _tma_position_ids(tma_structure)
    converted = _convert_definitions_doc(definitions_doc, all_pos_ids, sector_aliases or {})
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _convert_with_airac_overrides(
    doc: dict[str, object],
    convert_single,
) -> dict[str, object]:
    out = convert_single(doc)
    overrides = out.get("airac_overrides")
    if isinstance(overrides, dict):
        out["airac_overrides"] = {
            tier: convert_single(tier_doc) if isinstance(tier_doc, dict) else tier_doc
            for tier, tier_doc in overrides.items()
        }
    return out


def _convert_mva_single(doc: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in doc.items():
        if k == "airports" and "airport" not in doc:
            if isinstance(v, list) and len(v) == 1:
                out["airport"] = v[0]
            else:
                out["airport"] = deepcopy(v)
        else:
            out[k] = deepcopy(v)
    return out


def project_mva_payload(doc: dict[str, object]) -> bytes:
    """Convert schema-2 mva.json ('airports') to legacy ('airport')."""
    converted = _convert_with_airac_overrides(doc, _convert_mva_single)
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _convert_misc_row(row: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in row.items():
        if k == "runway_configs" and "configs" not in row:
            out["configs"] = deepcopy(v)
        else:
            out[k] = deepcopy(v)
    return out


def _convert_misc_dataset(ds: dict[str, object]) -> dict[str, object]:
    out = deepcopy(ds)
    for section in ("line_sections", "filled_polygons", "labels"):
        rows = out.get(section)
        if isinstance(rows, list):
            out[section] = [
                _convert_misc_row(row) if isinstance(row, dict) else row for row in rows
            ]
    return out


def _convert_misc_single(doc: dict[str, object]) -> dict[str, object]:
    out = _convert_misc_dataset(doc)
    if isinstance(out.get("drawings"), list):
        out["drawings"] = [
            _convert_misc_dataset(ds) if isinstance(ds, dict) else ds
            for ds in out["drawings"]  # type: ignore[union-attr]
        ]
    return out


def project_misc_drawings_payload(doc: dict[str, object]) -> bytes:
    """Convert schema-2 misc_drawings.json ('runway_configs') to legacy ('configs')."""
    converted = _convert_with_airac_overrides(doc, _convert_misc_single)
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _convert_proc_sid_entry(
    entry: dict[str, object],
    *,
    allow_aircraft_types: bool,
    sid_label: str,
    dropped_sids: list[tuple[str, list[str]]] | None,
) -> dict[str, object]:
    out_entry: dict[str, object] = {}
    reasons: list[str] = []
    for k, v in entry.items():
        if k == "not_for":
            reasons.append("not_for")
            continue
        if k == "only_for":
            if allow_aircraft_types and isinstance(v, dict):
                types = v.get("types")
                if isinstance(types, list) and types and "aircraft_types" not in entry:
                    out_entry["aircraft_types"] = deepcopy(types)
                wakes = v.get("wake_categories")
                if "wake_categories" in v and (not isinstance(wakes, list) or len(wakes) > 0):
                    reasons.append("only_for.wake_categories")
            else:
                if not isinstance(v, dict) or v.get("types") or v.get("wake_categories"):
                    reasons.append("only_for")
            continue
        out_entry[k] = deepcopy(v)
    if reasons and dropped_sids is not None:
        dropped_sids.append((sid_label, reasons))
    return out_entry


def _convert_proc_sids_bucket(
    sids: object,
    *,
    allow_aircraft_types: bool,
    prefix: str,
    dropped_sids: list[tuple[str, list[str]]] | None,
) -> object:
    if not isinstance(sids, dict):
        return deepcopy(sids)
    out: dict[str, object] = {}
    for sid_id, entry in sids.items():
        if isinstance(entry, dict):
            label = f"{prefix}{sid_id}" if prefix else str(sid_id)
            out[sid_id] = _convert_proc_sid_entry(
                entry,
                allow_aircraft_types=allow_aircraft_types,
                sid_label=label,
                dropped_sids=dropped_sids,
            )
        else:
            out[sid_id] = deepcopy(entry)
    return out


def _convert_proc_overrides(
    overrides: object,
    *,
    axis_name: str,
    dropped_sids: list[tuple[str, list[str]]] | None,
) -> object:
    if not isinstance(overrides, dict):
        return deepcopy(overrides)
    out: dict[str, object] = {}
    for override_key, override_payload in overrides.items():
        if not isinstance(override_payload, dict):
            out[override_key] = deepcopy(override_payload)
            continue
        tier_out: dict[str, object] = {}
        for k, v in override_payload.items():
            if k == "sids":
                tier_out[k] = _convert_proc_sids_bucket(
                    v,
                    allow_aircraft_types=False,
                    prefix=f"{axis_name}.{override_key}.sids.",
                    dropped_sids=dropped_sids,
                )
            else:
                tier_out[k] = deepcopy(v)
        out[override_key] = tier_out
    return out


def _convert_proc_single(
    doc: dict[str, object],
    *,
    dropped_sids: list[tuple[str, list[str]]] | None = None,
) -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in doc.items():
        if k == "runway_configs" and "configs" not in doc:
            out["configs"] = _convert_proc_overrides(
                v, axis_name="configs", dropped_sids=dropped_sids
            )
        elif k == "runway_ends" and "runways" not in doc:
            out["runways"] = _convert_proc_overrides(
                v, axis_name="runways", dropped_sids=dropped_sids
            )
        elif k in ("configs", "runways"):
            out[k] = _convert_proc_overrides(
                v, axis_name=k, dropped_sids=dropped_sids
            )
        elif k == "sids":
            out[k] = _convert_proc_sids_bucket(
                v, allow_aircraft_types=True, prefix="", dropped_sids=dropped_sids
            )
        else:
            out[k] = deepcopy(v)
    return out


def project_procedure_options_payload(doc: dict[str, object]) -> bytes:
    """Convert schema-2 procedure_options.json ('runway_configs'/'runway_ends'/'only_for') to legacy."""
    converted = _convert_with_airac_overrides(doc, _convert_proc_single)
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


CANONICAL_TO_LEGACY_UNIT_ALIASES: dict[str, str] = {
    "EDDF_APP": "DF_APP",
    "EDDF_TWR": "DF_TWR",
    "EDDM_APP": "DM_APP",
    "EDDM_TWR": "DM_TWR",
    "EGLL_APP": "HLR_APP",
    "EGLL_TWR": "HLR_TWR",
    "EGTT_CTR": "LON_CTR",
    "EHAM_APP": "AMS_APP",
    "EHAM_TWR": "AMS_TWR",
    "KATL_APP": "ATL_APP",
    "KATL_TWR": "ATL_TWR",
    "KBFI_TWR": "BFI_TWR",
    "KBOS_APP": "BOS_APP",
    "KBOS_TWR": "BOS_TWR",
    "KDCA_APP": "DCA_APP",
    "KDCA_TWR": "DCA_TWR",
    "KDEN_APP": "DEN_APP",
    "KDEN_TWR": "DEN_TWR",
    "KDFW_APP": "DFW_APP",
    "KDFW_TWR": "DFW_TWR",
    "KFRG_TWR": "FRG_TWR",
    "KJFK_APP": "JFK_APP",
    "KJFK_TWR": "JFK_TWR",
    "KLAX_APP": "LAX_APP",
    "KLAX_TWR": "LAX_TWR",
    "KLGB_TWR": "LGB_TWR",
    "KORD_APP": "CHI_APP",
    "KORD_TWR": "ORD_TWR",
    "KPDK_TWR": "PDK_TWR",
    "KSEA_APP": "SEA_APP",
    "KSEA_TWR": "SEA_TWR",
    "KSFO_APP": "SFO_APP",
    "KSFO_TWR": "SFO_TWR",
    "KZAU_CTR": "CHI_CTR",
    "KZBW_CTR": "BOS_CTR",
    "KZDC_CTR": "DCA_CTR",
    "KZDV_CTR": "KZDVCTR",
    "KZFW_CTR": "KZFWCTR",
    "KZLA_CTR": "KZLACTR",
    "KZNY_CTR": "KZNYCTR",
    "KZOA_CTR": "KZOACTR",
    "KZSE_CTR": "KZSECTR",
    "KZTL_CTR": "ATL_CTR",
    "LEBL_APP": "BCN_APP",
    "LEBL_TWR": "BCN_TWR",
    "LECB_CTR": "BCN_CTR",
    "LECM_CTR": "MAD_CTR",
    "LEDA_TWR": "LLE_TWR",
    "LEGE_TWR": "GIR_TWR",
    "LEMD_APP": "MAD_APP",
    "LEMD_TWR": "MAD_TWR",
    "LERS_TWR": "REU_TWR",
    "LFPG_APP": "CDG_APP",
    "LFPG_TWR": "CDG_TWR",
    "LFPO_APP": "ORY_APP",
    "LIRA_TWR": "CIA_TWR",
    "LIRF_APP": "ROM_APP",
    "LIRF_TWR": "FIU_TWR",
    "LIRR_CTR": "ROM_CTR",
    "LOVV_CTR": "VIE_CTR",
    "LOWW_APP": "VIE_APP",
    "LOWW_TWR": "VIE_TWR",
    "LSAS_CTR": "SWI_CTR",
    "LSZH_APP": "ZRH_APP",
    "LSZH_TWR": "ZRH_TWR",
}


def _convert_map_display_single(
    doc: dict[str, object],
    *,
    unit_aliases: dict[str, str] | None = None,
) -> dict[str, object]:
    out = deepcopy(doc)
    positions = out.get("positions")
    if not isinstance(positions, dict):
        return out
    aliases = {
        str(k).strip().upper(): str(v).strip()
        for k, v in (unit_aliases if unit_aliases is not None else CANONICAL_TO_LEGACY_UNIT_ALIASES).items()
        if str(k).strip() and str(v).strip()
    }
    existing_upper = {
        str(k).strip().upper()
        for k in positions
        if str(k).strip().upper() not in aliases
    }
    rewritten: dict[str, object] = {}
    changed = False
    for raw_key, block in positions.items():
        key_str = str(raw_key)
        upper = key_str.strip().upper()
        legacy = aliases.get(upper)
        if legacy and legacy != upper:
            changed = True
            if legacy.upper() not in existing_upper and legacy not in rewritten:
                rewritten[legacy] = block
        else:
            rewritten[key_str] = block
    if changed:
        out["positions"] = rewritten
    return out


def project_map_display_payload(
    doc: dict[str, object],
    *,
    unit_aliases: dict[str, str] | None = None,
) -> bytes:
    """Convert schema-2 map_display.json canonical unit IDs back to legacy aliases for old builds."""
    converted = _convert_with_airac_overrides(
        doc, lambda d: _convert_map_display_single(d, unit_aliases=unit_aliases)
    )
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


_KIND_CONVERTERS = {
    "mva": project_mva_payload,
    "misc_drawings": project_misc_drawings_payload,
    "procedure_options": project_procedure_options_payload,
    "map_display": project_map_display_payload,
}


def project_legacy_file_bytes(
    root: Path,
    repo_path: str,
    kind: str,
    *,
    force_generate: bool = False,
    files_index: dict[str, dict[str, object]] | None = None,
) -> bytes:
    """Return frozen legacy bytes when schema-2 source matches index.json, else generate."""
    raw_bytes = _canonical_lf((root / repo_path).read_bytes())
    index = load_frozen_files_index(root) if files_index is None else files_index
    if not force_generate:
        meta = index.get(repo_path)
        if isinstance(meta, dict) and meta.get("kind") == kind:
            raw_sha = hashlib.sha256(raw_bytes).hexdigest()
            if raw_sha == str(meta.get("source_sha256", "")):
                frozen_rel = str(meta.get("frozen_file", ""))
                frozen_path = root / FROZEN_DIR / frozen_rel
                if frozen_rel and frozen_path.is_file():
                    return _canonical_lf(frozen_path.read_bytes())
    converter_map = {
        "mva": _convert_mva_single,
        "misc_drawings": _convert_misc_single,
        "procedure_options": _convert_proc_single,
        "map_display": _convert_map_display_single,
    }
    doc = json.loads(raw_bytes.decode("utf-8"))
    converted = _convert_with_airac_overrides(doc, converter_map[kind])
    if converted == doc:
        return raw_bytes
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def project_map_display_default_bytes(
    root: Path,
    repo_path: str,
    *,
    force_generate: bool = False,
    files_index: dict[str, dict[str, object]] | None = None,
) -> bytes:
    """Return default-feed legacy map_display.json bytes (airac_overrides stripped, old unit IDs)."""
    raw_bytes = _canonical_lf((root / repo_path).read_bytes())
    index = load_frozen_files_index(root) if files_index is None else files_index
    if not force_generate:
        meta = index.get(repo_path)
        if isinstance(meta, dict) and meta.get("kind") == "map_display":
            raw_sha = hashlib.sha256(raw_bytes).hexdigest()
            if raw_sha == str(meta.get("source_sha256", "")):
                frozen_rel = str(meta.get("frozen_file", ""))
                frozen_path = root / FROZEN_DIR / frozen_rel
                if frozen_rel and frozen_path.is_file():
                    leg_bytes = _canonical_lf(frozen_path.read_bytes())
                    doc = json.loads(leg_bytes.decode("utf-8"))
                    if "airac_overrides" not in doc:
                        return leg_bytes
                    resolved = airac_overrides.resolve(doc, "")
                    return (json.dumps(resolved, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    doc = json.loads(raw_bytes.decode("utf-8"))
    base_doc = airac_overrides.resolve(doc, "") if "airac_overrides" in doc else doc
    converted = _convert_map_display_single(base_doc)
    if converted == base_doc and "airac_overrides" not in doc:
        return raw_bytes
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def project_procedure_options_default_bytes(
    root: Path,
    repo_path: str,
    *,
    force_generate: bool = False,
    files_index: dict[str, dict[str, object]] | None = None,
) -> bytes:
    """Return default-feed legacy procedure_options.json bytes (airac_overrides stripped)."""
    raw_bytes = _canonical_lf((root / repo_path).read_bytes())
    index = load_frozen_files_index(root) if files_index is None else files_index
    if not force_generate:
        meta = index.get(repo_path)
        if isinstance(meta, dict) and meta.get("kind") == "procedure_options":
            raw_sha = hashlib.sha256(raw_bytes).hexdigest()
            if raw_sha == str(meta.get("source_sha256", "")):
                frozen_rel = str(meta.get("frozen_file", ""))
                frozen_path = root / FROZEN_DIR / frozen_rel
                if frozen_rel and frozen_path.is_file():
                    leg_bytes = _canonical_lf(frozen_path.read_bytes())
                    doc = json.loads(leg_bytes.decode("utf-8"))
                    if "airac_overrides" not in doc:
                        return leg_bytes
                    resolved = airac_overrides.resolve(doc, "")
                    return (json.dumps(resolved, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    doc = json.loads(raw_bytes.decode("utf-8"))
    base_doc = airac_overrides.resolve(doc, "") if "airac_overrides" in doc else doc
    dropped_sids: list[tuple[str, list[str]]] = []
    converted = _convert_proc_single(base_doc, dropped_sids=dropped_sids)
    for sid_label, reasons in dropped_sids:
        print(
            f"[procedure_options] {repo_path} SID {sid_label}: dropped {', '.join(reasons)} (unsupported by legacy builds)",
            file=sys.stderr,
        )
    if converted == base_doc and "airac_overrides" not in doc:
        return raw_bytes
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _file_meta(raw_bytes: bytes) -> tuple[str, int]:
    return hashlib.sha256(raw_bytes).hexdigest(), len(raw_bytes)


def project_release_dataset_feeds(
    root: Path,
    gated: dict[str, object],
    *,
    kind: str,
    projected_bytes: dict[str, bytes] | None = None,
    force_generate: bool = False,
) -> tuple[dict[str, bytes], dict[str, str]]:
    """Apply legacy projections to default & full manifests for mva, misc_drawings, or sector_data.

    Returns ``(generated_bytes, archive_sources)`` for full archives; default archives read
    projected bytes for matching repo_paths.
    """
    if kind == "sector_data":
        generated = dict(projected_bytes or {})
        archive_sources: dict[str, str] = {}
        new_full_entries: list[dict[str, object]] = []
        raw_entries = gated.get("full_entries", [])
        if isinstance(raw_entries, list):
            airac_override_ids = {
                str(e.get("id", ""))
                for e in raw_entries
                if isinstance(e, dict)
                and isinstance(e.get("requires"), list)
                and airac_overrides.CAPABILITY in e["requires"]
            }
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    continue
                files = entry.get("files", {})
                if not isinstance(files, dict):
                    new_full_entries.append(entry)
                    continue
                for file_entry in files.values():
                    if isinstance(file_entry, dict) and file_entry.get("repo_path"):
                        rp = str(file_entry["repo_path"])
                        orig = rp[len("airac_variants/") :] if rp.startswith("airac_variants/") else rp
                        archive_sources[rp] = orig
                reqs = list(entry.get("requires", [])) if isinstance(entry.get("requires"), list) else []
                def_entry = files.get("definitions")
                if not isinstance(def_entry, dict):
                    new_full_entries.append(entry)
                    continue
                def_repo = str(def_entry.get("repo_path", ""))
                orig_def = def_repo[len("airac_variants/") :] if def_repo.startswith("airac_variants/") else def_repo
                disk_path = root / orig_def if orig_def else None
                disk_bytes = _canonical_lf(disk_path.read_bytes()) if disk_path and disk_path.is_file() else None
                leg_bytes = generated.get(orig_def)
                has_def_variant = disk_bytes is not None and leg_bytes is not None and leg_bytes != disk_bytes
                has_def_overrides = (
                    disk_bytes is not None
                    and "airac_overrides" in json.loads(disk_bytes.decode("utf-8"))
                )
                if AIRSPACE_FILES_CAPABILITY in reqs or airac_overrides.CAPABILITY in reqs:
                    if has_def_variant and not def_repo.startswith("airac_variants/"):
                        variant_repo = f"airac_variants/{orig_def}"
                        files["definitions"] = _file_entry(
                            variant_repo, disk_bytes, requires=[AIRSPACE_FILES_CAPABILITY]
                        )
                        extra = {AIRSPACE_FILES_CAPABILITY}
                        if has_def_overrides:
                            extra.add(airac_overrides.CAPABILITY)
                        entry["requires"] = sorted(set(reqs) | extra)
                        generated[variant_repo] = disk_bytes
                        archive_sources[variant_repo] = variant_repo
                    elif AIRSPACE_FILES_CAPABILITY not in reqs:
                        entry["requires"] = sorted(set(reqs) | {AIRSPACE_FILES_CAPABILITY})
                    new_full_entries.append(entry)
                    continue
                new_full_entries.append(entry)
                if has_def_variant and not (
                    has_def_overrides and str(entry.get("id", "")) in airac_override_ids
                ):
                    s2_files = {k: dict(v) for k, v in files.items() if isinstance(v, dict)}
                    variant_repo = f"airac_variants/{orig_def}"
                    s2_files["definitions"] = _file_entry(
                        variant_repo, disk_bytes, requires=[AIRSPACE_FILES_CAPABILITY]
                    )
                    extra_reqs = {AIRSPACE_FILES_CAPABILITY}
                    if has_def_overrides:
                        extra_reqs.add(airac_overrides.CAPABILITY)
                    s2_entry: dict[str, object] = {
                        "id": entry["id"],
                        "requires": sorted(set(reqs) | extra_reqs),
                        "files": s2_files,
                    }
                    if "channels" in entry:
                        s2_entry["channels"] = list(entry["channels"])
                    new_full_entries.append(s2_entry)
                    generated[variant_repo] = disk_bytes
                    archive_sources[variant_repo] = variant_repo
        gated["full_entries"] = new_full_entries
        return generated, archive_sources

    files_index = load_frozen_files_index(root)
    generated = {}
    default_manifest = gated.get("default", {})
    if isinstance(default_manifest, dict):
        for entry in default_manifest.values():
            if not isinstance(entry, dict):
                continue
            rp = str(entry.get("repo_path", ""))
            if not rp or not (root / rp).is_file():
                continue
            leg_bytes = generated.get(rp)
            if leg_bytes is None:
                leg_bytes = project_legacy_file_bytes(
                    root, rp, kind, force_generate=force_generate, files_index=files_index
                )
                generated[rp] = leg_bytes
            sha, size = _file_meta(leg_bytes)
            entry["sha256"] = sha
            entry["size_bytes"] = size

    archive_sources = {}
    new_full_entries = []
    raw_entries = gated.get("full_entries", [])
    if isinstance(raw_entries, list):
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            rp = str(entry.get("repo_path", ""))
            orig = rp[len("airac_variants/") :] if rp.startswith("airac_variants/") else rp
            if not orig or not (root / orig).is_file():
                new_full_entries.append(entry)
                if rp:
                    archive_sources[rp] = orig or rp
                continue
            disk_bytes = _canonical_lf((root / orig).read_bytes())
            leg_bytes = generated.get(orig)
            if leg_bytes is None:
                leg_bytes = project_legacy_file_bytes(
                    root, orig, kind, force_generate=force_generate, files_index=files_index
                )
                generated[orig] = leg_bytes
            reqs = list(entry.get("requires", [])) if isinstance(entry.get("requires"), list) else []
            if AIRSPACE_FILES_CAPABILITY in reqs:
                new_full_entries.append(entry)
                archive_sources[rp] = orig
                continue
            if leg_bytes != disk_bytes:
                sha, size = _file_meta(leg_bytes)
                legacy_entry = dict(entry)
                legacy_entry["sha256"] = sha
                legacy_entry["size_bytes"] = size
                new_full_entries.append(legacy_entry)
                archive_sources[rp] = orig

                variant_repo = f"airac_variants/{orig}"
                d_sha, d_size = _file_meta(disk_bytes)
                s2_entry = dict(entry)
                s2_entry["repo_path"] = variant_repo
                s2_entry["sha256"] = d_sha
                s2_entry["size_bytes"] = d_size
                s2_entry["requires"] = sorted(set(reqs) | {AIRSPACE_FILES_CAPABILITY})
                new_full_entries.append(s2_entry)
                generated[variant_repo] = disk_bytes
                archive_sources[variant_repo] = orig
            else:
                new_full_entries.append(entry)
                archive_sources[rp] = orig
    gated["full_entries"] = new_full_entries
    return generated, archive_sources


def build_sector_release_projection(
    root: Path,
    source_bundles: dict[str, dict[str, object]],
    *,
    force_generate: bool = False,
) -> dict[str, object]:
    """Augment schema-2 source bundles with frozen or projected legacy and schema-1 tma files.

    Returns ``{"bundles", "projected_bytes", "bundle_paths", "frozen_bundles", "generated_bundles"}``.
    """
    index_bundles = load_frozen_index(root)
    all_acc_units: dict[str, dict] = {}
    for bundle_entry in source_bundles.values():
        files = bundle_entry.get("files", {}) if isinstance(bundle_entry, dict) else {}
        acc_entry = files.get("acc_structure") if isinstance(files, dict) else None
        if isinstance(acc_entry, dict):
            acc_path = root / str(acc_entry["repo_path"])
            payload = json.loads(acc_path.read_text(encoding="utf-8"))
            for unit in payload.get("units", []):
                if isinstance(unit, dict) and unit.get("id"):
                    all_acc_units[str(unit["id"]).strip()] = unit

    projected_bundles: dict[str, dict[str, object]] = {}
    projected_bytes: dict[str, bytes] = {}
    bundle_paths: dict[str, str] = {}
    frozen_bundles: list[str] = []
    generated_bundles: list[str] = []

    for bundle_path, bundle_entry in source_bundles.items():
        if not isinstance(bundle_entry, dict) or not isinstance(bundle_entry.get("files"), dict):
            raise ValueError(f"{bundle_path}: invalid source bundle entry")
        src_files = bundle_entry["files"]
        out_files = {kind: dict(entry) for kind, entry in src_files.items() if isinstance(entry, dict)}

        if "tma_structure" in out_files:
            index_entry = index_bundles.get(bundle_path)
            frozen_files = (
                None
                if force_generate
                else _frozen_files_if_fresh(root, bundle_path, out_files, index_entry)
            )
            cfg_repo = f"{bundle_path}/sector_configs.json"
            inf_repo = f"{bundle_path}/sector_influence.json"
            tma_repo = f"{bundle_path}/tma.json"
            def_repo = (
                str(out_files["definitions"]["repo_path"])
                if isinstance(out_files.get("definitions"), dict)
                else f"{bundle_path}/sector_definitions.json"
            )

            if frozen_files is not None:
                bundle_paths[bundle_path] = "frozen"
                frozen_bundles.append(bundle_path)
                cfg_bytes = frozen_files["sector_configs.json"]
                inf_bytes = frozen_files["sector_influence.json"]
                def_bytes = frozen_files["sector_definitions.json"]
                projected_bytes[cfg_repo] = cfg_bytes
                projected_bytes[inf_repo] = inf_bytes
                projected_bytes[def_repo] = def_bytes
                out_files["configs"] = _file_entry(cfg_repo, cfg_bytes)
                out_files["influence"] = _file_entry(inf_repo, inf_bytes)
                out_files["definitions"] = _file_entry(def_repo, def_bytes)
                if "tma.json" in frozen_files:
                    tma_bytes = frozen_files["tma.json"]
                    projected_bytes[tma_repo] = tma_bytes
                    out_files["tma"] = _file_entry(tma_repo, tma_bytes, requires=[TMA_FILE_CAPABILITY])
            else:
                bundle_paths[bundle_path] = "generated"
                generated_bundles.append(bundle_path)
                tma_struct_path = root / str(out_files["tma_structure"]["repo_path"])
                tma_structure = json.loads(tma_struct_path.read_text(encoding="utf-8"))
                meta = index_entry or {}
                cfg_payload, inf_payload = project_configs_and_influence(
                    tma_structure,
                    sector_aliases=meta.get("sector_aliases"),  # type: ignore[arg-type]
                    configs_airport=meta.get("configs_airport"),  # type: ignore[arg-type]
                    influence_airport=meta.get("influence_airport"),  # type: ignore[arg-type]
                    auto_airport_for_non_prefixed=index_entry is None,
                )
                cfg_bytes = (json.dumps(cfg_payload, indent=2) + "\n").encode("utf-8")
                inf_bytes = (json.dumps(inf_payload, indent=2) + "\n").encode("utf-8")
                projected_bytes[cfg_repo] = cfg_bytes
                projected_bytes[inf_repo] = inf_bytes
                out_files["configs"] = _file_entry(cfg_repo, cfg_bytes)
                out_files["influence"] = _file_entry(inf_repo, inf_bytes)

                if isinstance(out_files.get("definitions"), dict):
                    def_raw = _canonical_lf((root / def_repo).read_bytes())
                    defs_doc = json.loads(def_raw.decode("utf-8"))
                    all_pos_ids = _tma_position_ids(tma_structure)
                    default_defs = _resolve_default_doc(defs_doc)
                    converted_defs = _convert_definitions_doc(
                        default_defs, all_pos_ids, meta.get("sector_aliases") or {}  # type: ignore[arg-type]
                    )
                    if converted_defs != defs_doc:
                        def_bytes = (
                            json.dumps(converted_defs, indent=2, ensure_ascii=False) + "\n"
                        ).encode("utf-8")
                        projected_bytes[def_repo] = def_bytes
                        out_files["definitions"] = _file_entry(def_repo, def_bytes)

                if "tma_coordination" in out_files:
                    coord_path = root / str(out_files["tma_coordination"]["repo_path"])
                    tma_coordination = json.loads(coord_path.read_text(encoding="utf-8"))
                    acc_units = _collect_acc_units_for_bundle(root, bundle_path, all_acc_units)
                    bundle_key = Path(bundle_path).name
                    tma_payload = project_schema1_tma(
                        tma_structure,
                        tma_coordination,
                        acc_units,
                        bundle_key,
                        unit_aliases=meta.get("unit_aliases"),  # type: ignore[arg-type]
                        tma_name=meta.get("tma_name"),  # type: ignore[arg-type]
                    )
                    tma_bytes = (json.dumps(tma_payload, indent=2) + "\n").encode("utf-8")
                    projected_bytes[tma_repo] = tma_bytes
                    out_files["tma"] = _file_entry(tma_repo, tma_bytes, requires=[TMA_FILE_CAPABILITY])

        projected_bundles[bundle_path] = {"files": out_files}

    return {
        "bundles": dict(sorted(projected_bundles.items())),
        "projected_bytes": projected_bytes,
        "bundle_paths": dict(sorted(bundle_paths.items())),
        "frozen_bundles": sorted(frozen_bundles),
        "generated_bundles": sorted(generated_bundles),
    }


def format_projection_report(projection: dict[str, object]) -> str:
    frozen = list(projection.get("frozen_bundles", []))  # type: ignore[arg-type]
    generated = list(projection.get("generated_bundles", []))  # type: ignore[arg-type]
    if not generated:
        return f"Sector projection: {len(frozen)} frozen, 0 generated."
    return (
        f"Sector projection: {len(frozen)} frozen, {len(generated)} generated "
        f"({', '.join(generated)})."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, help="Write projected legacy files into this directory")
    parser.add_argument("--validate-only", action="store_true", help="Validate projection without writing")
    parser.add_argument("--force-generate", action="store_true", help="Ignore frozen snapshots and generate all bundles from schema 2")
    args = parser.parse_args()

    try:
        from . import sector_data_manifest
    except ImportError:
        if str(Path(__file__).resolve().parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
        import sector_data_manifest

    try:
        source_manifest = sector_data_manifest.build_manifest(ROOT, commit_sha="projection")
        projection = build_sector_release_projection(
            ROOT, source_manifest["bundles"], force_generate=args.force_generate
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    projected_bytes: dict[str, bytes] = projection["projected_bytes"]  # type: ignore[assignment]
    if args.out_dir:
        for repo_path, raw_bytes in sorted(projected_bytes.items()):
            dest = args.out_dir / repo_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw_bytes)
        print(f"Wrote {len(projected_bytes)} projected legacy files to {args.out_dir}")
    elif args.validate_only:
        files_index = load_frozen_files_index(ROOT)
        per_file_count = 0
        for repo_path, meta in sorted(files_index.items()):
            kind = str(meta.get("kind", ""))
            _ = project_legacy_file_bytes(ROOT, repo_path, kind, force_generate=args.force_generate, files_index=files_index)
            per_file_count += 1
        print(
            f"Validated {len(projected_bytes)} projected legacy bundle files across {len(projection['bundles'])} bundles "
            f"and {per_file_count} projected dataset files."
        )
    else:
        print(f"Projected {len(projected_bytes)} legacy files.")
    print(format_projection_report(projection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
