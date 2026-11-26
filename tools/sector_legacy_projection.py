#!/usr/bin/env python3
"""Project schema-3 bundles and dataset files back into legacy shapes for older builds.

Default (legacy) builds read ``sector_configs.json`` and ``sector_influence.json``
and scalar ``sector_definitions.json`` at each terminal bundle path, while
``community.tma_file`` builds read schema-1 ``tma.json`` from the full feed.
Skinned countries' legacy ``colors.json``/``style.json``, ``procedure_options.json``,
``constraints.json``, ``map_display.json``, and ``visual_*.json`` also ship through
this projection for older builds.

``release/legacy_frozen/`` holds the verbatim legacy bytes captured from ``main``
plus ``release/legacy_frozen/index.json``. A bundle with a complete frozen snapshot
ships those bytes verbatim to legacy builds, whatever its schema-3 sources now say;
only a bundle without an index entry or a complete snapshot (or ``--force-generate``)
regenerates the legacy shapes from schema 3. The cost: sector edits no longer reach
builds older than schema 3 until their snapshot is refreshed by hand.
"""
from __future__ import annotations

try:
    from . import airac_overrides, release_gates, schema3_features, tma_checker
except ImportError:  # run as a script, or loaded by file path (tests)
    import sys
    from pathlib import Path

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import airac_overrides
    import release_gates
    import schema3_features
    import tma_checker

import argparse
from copy import deepcopy
import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent.parent
FROZEN_DIR = Path("release") / "legacy_frozen"
FROZEN_INDEX_PATH = FROZEN_DIR / "index.json"
TMA_FILE_CAPABILITY = "community.tma_file"
AIRSPACE_FILES_CAPABILITY = "community.airspace_files"

_BUNDLE_PATH_TO_LEGACY = {
    "L/LE/LECB/LECP/PALMA_TMA": "L/LE/LECB/LECB_E/PALMA_TMA",
    "L/LE/LECB/LECL/VALENCIA_TMA": "L/LE/LECB/LECB_W/VALENCIA_TMA",
}
_LEGACY_TO_BUNDLE_PATH = {v: k for k, v in _BUNDLE_PATH_TO_LEGACY.items()}

_LEG_TYPE_TO_TERM = {
    "initial_fix": "IF",
    "track_to_fix": "TF",
    "direct_to_fix": "DF",
    "course_to_fix": "CF",
    "course_to_altitude": "CA",
    "heading_to_altitude": "VA",
    "heading_to_manual": "VM",
    "course_to_manual": "FM",
    "from_fix_manual": "FM",
    "radius_to_fix": "RF",
    "constant_radius_arc": "RF",
    "arc_to_fix": "AF",
    "dme_arc": "AF",
    "course_to_dme": "CD",
    "course_to_intercept": "CI",
    "course_to_radial": "CR",
    "fix_to_altitude": "FA",
    "track_to_distance": "FC",
    "fix_to_dme": "FD",
    "heading_to_dme": "VD",
    "heading_to_intercept": "VI",
    "heading_to_radial": "VR",
    "hold_manual": "HM",
    "hold_single": "HF",
}


def legacy_path_for_bundle(bundle_path: str, index_entry: dict[str, object] | None = None) -> str:
    if isinstance(index_entry, dict) and index_entry.get("legacy_bundle_path"):
        return str(index_entry["legacy_bundle_path"])
    return _BUNDLE_PATH_TO_LEGACY.get(bundle_path, bundle_path)


def schema3_path_for_legacy_bundle(legacy_bundle_path: str) -> str:
    return _LEGACY_TO_BUNDLE_PATH.get(legacy_bundle_path, legacy_bundle_path)


def _canonical_lf(raw_bytes: bytes) -> bytes:
    return raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _sha256_file(path: Path) -> str:
    """Hash of a source file's content: JSON by its parsed value, so formatting never unfreezes a bundle."""
    raw = _canonical_lf(path.read_bytes())
    if path.suffix == ".json":
        value = json.loads(raw.decode("utf-8-sig"))
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_frozen_index(root: Path) -> dict[str, dict[str, object]]:
    index_path = root / FROZEN_INDEX_PATH
    if not index_path.is_file():
        return {}
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    bundles = payload.get("bundles", {})
    if not isinstance(bundles, dict):
        return {}
    return {
        str(k).strip().replace("\\", "/"): v
        for k, v in bundles.items()
        if isinstance(v, dict)
    }


def load_frozen_files_index(root: Path) -> dict[str, dict[str, object]]:
    """Return per-file frozen snapshot metadata keyed by legacy repo_path."""
    index_path = root / FROZEN_INDEX_PATH
    if not index_path.is_file():
        return {}
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    files = payload.get("files", {})
    if not isinstance(files, dict):
        return {}
    return {
        str(k).strip().replace("\\", "/"): v
        for k, v in files.items()
        if isinstance(v, dict)
    }


def _find_ancestor_acc_definitions(root: Path, bundle_path: str) -> Path | None:
    cur = (root / bundle_path).parent
    while cur != root and cur.parent != cur:
        for fname in ("acc_definitions.json", "acc_structure.json"):
            cand = cur / fname
            if cand.is_file():
                return cand
        cur = cur.parent
    return None


def _resolve_default_doc(document: dict) -> dict:
    if "airac_overrides" in document:
        return airac_overrides.resolve(document, "")
    return document


def _pos_lookup(tma_defs: dict) -> dict[str, dict]:
    by_cs: dict[str, dict] = {}
    for pos in tma_defs.get("positions", []):
        if isinstance(pos, dict) and pos.get("call_sign"):
            by_cs[str(pos["call_sign"]).strip()] = pos
    return by_cs


def _unit_lookup(tma_defs: dict) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for unit in tma_defs.get("units", []):
        if isinstance(unit, dict) and unit.get("id"):
            by_id[str(unit["id"]).strip()] = unit
    return by_id


def _zone_sector_set(tma_defs: dict) -> set[str]:
    out: set[str] = set()
    for z in tma_defs.get("zones", []):
        if isinstance(z, dict) and z.get("sector"):
            out.add(str(z["sector"]).strip().upper())
    return out


def _derive_served_airports(tma_defs: dict, tma_layout: dict | None = None) -> list[str]:
    airports: list[str] = []
    if tma_layout is not None:
        layout_doc = _resolve_default_doc(tma_layout)
        configs_by_unit = layout_doc.get("configurations", {})
        if isinstance(configs_by_unit, dict):
            for unit_cfgs in configs_by_unit.values():
                if not isinstance(unit_cfgs, dict):
                    continue
                for cfg in unit_cfgs.values():
                    if not isinstance(cfg, dict):
                        continue
                    for airport in cfg.get("airports", []):
                        code = str(airport).strip().upper()
                        if code and code not in airports:
                            airports.append(code)
    for unit in tma_defs.get("units", []):
        if not isinstance(unit, dict):
            continue
        code = str(unit.get("airport", "")).strip().upper()
        if code and code not in airports:
            airports.append(code)
    for zone in tma_defs.get("zones", []):
        if not isinstance(zone, dict):
            continue
        code = str(zone.get("airport", "")).strip().upper()
        if code and code not in airports:
            airports.append(code)
    return airports


def _schema3_layouts(
    tma_defs: dict,
    tma_layout: dict,
    *,
    acc_positions_by_cs: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Return (radar_layouts, tower_zone_layouts) normalized cleanly for legacy projection."""
    defs_doc = _resolve_default_doc(tma_defs)
    layout_doc = _resolve_default_doc(tma_layout)
    zones_set = _zone_sector_set(defs_doc)
    pos_by_cs = _pos_lookup(defs_doc)
    if acc_positions_by_cs:
        for k, v in acc_positions_by_cs.items():
            pos_by_cs.setdefault(k, v)
    unit_by_id = _unit_lookup(defs_doc)
    served = _derive_served_airports(defs_doc, layout_doc)

    radar_layouts: list[dict] = []
    tower_layouts: list[dict] = []
    configs_by_unit = layout_doc.get("configurations", {})
    if not isinstance(configs_by_unit, dict):
        return radar_layouts, tower_layouts

    for owner_unit_id, unit_cfgs in configs_by_unit.items():
        if not isinstance(unit_cfgs, dict):
            continue
        owner_unit = unit_by_id.get(str(owner_unit_id).strip(), {})
        for cfg_id, cfg in unit_cfgs.items():
            if not isinstance(cfg, dict):
                continue
            raw_positions = cfg.get("positions", {})
            if not isinstance(raw_positions, dict):
                continue
            cfg_airports = [
                str(a).strip().upper()
                for a in cfg.get("airports", [])
                if str(a).strip()
            ]
            if not cfg_airports:
                apt = str(owner_unit.get("airport", "")).strip().upper()
                if apt:
                    cfg_airports = [apt]
                elif len(served) == 1:
                    cfg_airports = list(served)
            positions_out: list[dict] = []
            zone_positions_out: list[dict] = []
            for cs, raw_secs in raw_positions.items():
                cs_str = str(cs).strip()
                pinfo = pos_by_cs.get(cs_str, {})
                secs = [str(s).strip().upper() for s in raw_secs if str(s).strip()] if isinstance(raw_secs, list) else []
                primary = [s for s in secs if s not in zones_set]
                attached_zones = [s for s in secs if s in zones_set]
                uid = str(pinfo.get("unit", owner_unit_id)).strip()
                freq = str(pinfo.get("frequency", "")).strip()
                pos_name = str(pinfo.get("name", "")).strip() or (primary[0] if primary else cs_str)
                if primary:
                    positions_out.append({
                        "sector": "~".join(primary) if len(primary) > 1 else primary[0],
                        "sectors_list": primary,
                        "name": pos_name,
                        "code": cs_str,
                        "unit": uid,
                        "frequency": freq,
                        "zones": attached_zones,
                    })
                elif attached_zones:
                    zone_positions_out.append({
                        "unit": uid,
                        "name": str(pinfo.get("name", "TWR")).strip() or "TWR",
                        "code": cs_str,
                        "frequency": freq,
                        "sectors": attached_zones,
                    })
            layout_row = {
                "id": str(cfg_id).strip(),
                "owner_unit": str(owner_unit_id).strip(),
                "airports": cfg_airports,
                "runways": cfg.get("valid_for_runways", cfg.get("runways", {})),
                "positions": positions_out,
                "on_duty": cfg.get("on_duty", []),
            }
            if positions_out:
                radar_layouts.append(layout_row)
            elif zone_positions_out:
                tower_layouts.append({"id": str(cfg_id).strip(), "zones_on_duty": zone_positions_out})
    return radar_layouts, tower_layouts


def project_configs_and_influence(
    tma_defs: dict,
    tma_layout: dict | None = None,
    *,
    sector_aliases: dict[str, list[str]] | None = None,
    configs_airport: str | None = None,
    influence_airport: str | None = None,
    auto_airport_for_non_prefixed: bool = False,
) -> tuple[dict, dict]:
    """Generate (sector_configs_payload, sector_influence_payload) from schema-3 TMA files."""
    defs_doc = _resolve_default_doc(tma_defs)
    if tma_layout is None:
        # Compatibility if schema-2 layout list already passed directly
        radar_layouts = defs_doc.get("layouts", [])
    else:
        radar_layouts, _ = _schema3_layouts(defs_doc, tma_layout)

    aliases = {
        str(k).strip().upper(): [str(item).strip().upper() for item in v if str(item).strip()]
        for k, v in (sector_aliases or {}).items()
        if isinstance(v, list)
    }

    sector_configs: list[dict] = []
    seen_config_ids: set[str] = set()
    influence_order: list[str] = []
    influence_airports: dict[str, list[str]] = {}

    for layout in radar_layouts:
        if not isinstance(layout, dict):
            continue
        config_id = str(layout.get("id", "")).strip().upper()
        if not config_id or config_id in seen_config_ids:
            continue
        seen_config_ids.add(config_id)
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
            raw_list = pos.get("sectors_list")
            if isinstance(raw_list, list) and len(raw_list) > 1:
                parts = [str(s).strip().upper() for s in raw_list if str(s).strip()]
            else:
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

            pos_airports = layout_airports
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

    served_airports = _derive_served_airports(defs_doc, tma_layout)
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


def _agreement_specificity(row: dict) -> int:
    score = 0
    if row.get("runways"):
        score += 20
    if row.get("fix"):
        score += 10
    if row.get("departs") and row.get("arrives"):
        score += 5
    return score


def project_schema1_tma(
    tma_defs: dict,
    tma_layout: dict | None,
    tma_coordination: dict | None,
    acc_units_by_id: dict[str, dict],
    bundle_key: str,
    *,
    acc_positions_by_cs: dict[str, dict] | None = None,
    unit_aliases: dict[str, str] | None = None,
    tma_name: str | None = None,
) -> dict:
    """Reconstruct a schema-1 tma.json payload from schema-3 files and ACC center units."""
    defs_doc = _resolve_default_doc(tma_defs)
    if tma_layout is not None:
        radar_layouts, tower_layouts = _schema3_layouts(
            defs_doc, tma_layout, acc_positions_by_cs=acc_positions_by_cs
        )
    else:
        radar_layouts = deepcopy(defs_doc.get("layouts", []))
        tower_layouts = []

    # Reconstruct schema-1 units with populated `frequencies` arrays
    freqs_by_unit: dict[str, list[str]] = {}
    for pos in defs_doc.get("positions", []):
        if isinstance(pos, dict) and pos.get("unit") and pos.get("frequency"):
            uid = str(pos["unit"]).strip()
            fq = str(pos["frequency"]).strip()
            freqs_by_unit.setdefault(uid, [])
            if fq not in freqs_by_unit[uid]:
                freqs_by_unit[uid].append(fq)

    units: list[dict] = []
    present_ids: set[str] = set()
    for raw_u in defs_doc.get("units", []):
        if not isinstance(raw_u, dict) or not raw_u.get("id"):
            continue
        u = deepcopy(raw_u)
        uid = str(u["id"]).strip()
        present_ids.add(uid)
        merged_freqs: list[str] = list(freqs_by_unit.get(uid, []))
        for fq in u.pop("unassigned_frequencies", []) or []:
            fq_s = str(fq).strip()
            if fq_s and fq_s not in merged_freqs:
                merged_freqs.append(fq_s)
        for fq in u.get("frequencies", []) or []:
            fq_s = str(fq).strip()
            if fq_s and fq_s not in merged_freqs:
                merged_freqs.append(fq_s)
        if merged_freqs:
            u["frequencies"] = merged_freqs
        u.pop("part_of", None)
        u.pop("title", None)
        units.append(u)

    referenced: set[str] = set()
    for layout in radar_layouts:
        for pos in layout.get("positions", []):
            if pos.get("unit"):
                referenced.add(str(pos["unit"]).strip())
        for duty in layout.get("on_duty", []):
            if isinstance(duty, dict) and duty.get("unit"):
                referenced.add(str(duty["unit"]).strip())
    for tl in tower_layouts:
        for d in tl.get("zones_on_duty", []):
            if d.get("unit"):
                referenced.add(str(d["unit"]).strip())
    if isinstance(tma_coordination, dict):
        for agr in tma_coordination.get("agreements", []):
            if not isinstance(agr, dict):
                continue
            for key in ("from", "to"):
                if agr.get(key):
                    referenced.add(str(agr[key]).strip())
            ga = agr.get("go_around")
            if isinstance(ga, dict) and ga.get("to"):
                referenced.add(str(ga["to"]).strip())

    for uid in sorted(referenced):
        if uid not in present_ids and uid in acc_units_by_id:
            acc_u = deepcopy(acc_units_by_id[uid])
            acc_u.pop("part_of", None)
            acc_u.pop("title", None)
            if "frequencies" not in acc_u:
                acc_freqs = list(acc_u.pop("unassigned_frequencies", []) or [])
                if acc_positions_by_cs:
                    for p in acc_positions_by_cs.values():
                        if str(p.get("unit", "")).strip() == uid and p.get("frequency"):
                            fq_s = str(p["frequency"]).strip()
                            if fq_s not in acc_freqs:
                                acc_freqs.append(fq_s)
                if acc_freqs:
                    acc_u["frequencies"] = acc_freqs
            units.append(acc_u)
            present_ids.add(uid)

    aliases: dict[str, str] = {}
    if unit_aliases:
        for k, v in unit_aliases.items():
            aliases[str(k).strip()] = str(v).strip()

    for unit in units:
        uid = str(unit.get("id", "")).strip()
        if uid in aliases:
            unit["id"] = aliases[uid]

    default_on_duty: list[dict] = []
    seen_duty_codes: set[str] = set()
    for tl in tower_layouts:
        for d in tl.get("zones_on_duty", []):
            code = str(d.get("code", "")).strip()
            if code and code not in seen_duty_codes:
                seen_duty_codes.add(code)
                entry = deepcopy(d)
                if entry.get("unit") in aliases:
                    entry["unit"] = aliases[entry["unit"]]
                default_on_duty.append(entry)

    layouts_out: list[dict] = []
    for layout in radar_layouts:
        l_out: dict[str, object] = {"id": layout["id"]}
        if layout.get("runways"):
            l_out["runways"] = deepcopy(layout["runways"])
        positions_out: list[dict] = []
        for idx, pos in enumerate(layout.get("positions", [])):
            p_out = {
                "sector": str(pos.get("sector", "")).split("~")[0],
                "name": pos.get("name", ""),
                "code": pos.get("code", ""),
                "unit": aliases.get(str(pos.get("unit", "")), str(pos.get("unit", ""))),
                "frequency": pos.get("frequency", ""),
            }
            if pos.get("zones"):
                p_out["zones"] = list(pos["zones"])
            if idx == 0 and layout.get("airports"):
                p_out["airports"] = list(layout["airports"])
            positions_out.append(p_out)
        l_out["positions"] = positions_out
        on_duty = []
        for duty in layout.get("on_duty", []) or default_on_duty:
            if not isinstance(duty, dict):
                continue
            d_copy = deepcopy(duty)
            if d_copy.get("unit") in aliases:
                d_copy["unit"] = aliases[d_copy["unit"]]
            on_duty.append(d_copy)
        if on_duty:
            l_out["on_duty"] = on_duty
        layouts_out.append(l_out)

    resolved_name = (tma_name or "").strip() or _derive_tma_name(bundle_key)
    out: dict[str, object] = {
        "schema": 1,
        "tma": {"id": bundle_key, "name": resolved_name},
        "airports": _derive_served_airports(defs_doc, tma_layout),
        "units": units,
    }
    if "zones" in defs_doc:
        out["zones"] = deepcopy(defs_doc["zones"])
    if tma_layout is not None:
        layout_doc = _resolve_default_doc(tma_layout)
        combos = layout_doc.get("runway_combinations")
        if isinstance(combos, list) and combos:
            out["configurations"] = [
                {
                    "id": str(c.get("id", "")),
                    "name": str(c.get("title", "")),
                    "airports": deepcopy(c.get("airports", {})),
                }
                for c in combos
                if isinstance(c, dict)
            ]
    out["layouts"] = layouts_out
    if isinstance(tma_coordination, dict) and tma_coordination.get("agreements"):
        agreements_out: list[dict] = []
        for idx, agr in enumerate(tma_coordination["agreements"]):
            if not isinstance(agr, dict):
                continue
            row = deepcopy(agr)
            for key in ("from", "to"):
                if row.get(key) in aliases:
                    row[key] = aliases[row[key]]
            if "level" in row:
                lvl = row.pop("level")
                rel = str(row.pop("release", "")).strip()
                has_dep = bool(row.get("departs"))
                has_arr = bool(row.get("arrives"))
                if has_dep and not has_arr:
                    row["climb"] = lvl
                elif has_arr and not has_dep:
                    row["descent"] = lvl
                elif rel == "climb":
                    row["climb"] = lvl
                elif rel == "descent":
                    row["descent"] = lvl
                else:
                    row["climb"] = lvl
                    row["descent"] = lvl
                if rel and "release_kind" not in row:
                    row["release_kind"] = rel
            if "priority" not in row:
                row["priority"] = 10 + _agreement_specificity(row)
            ga = row.get("go_around")
            if isinstance(ga, dict):
                if ga.get("to") in aliases:
                    ga["to"] = aliases[ga["to"]]
                if "level" in ga and "climb" not in ga:
                    ga["climb"] = ga.pop("level")
            fix = row.get("fix")
            if isinstance(fix, list) and len(fix) == 1:
                row["fix"] = fix[0]
            agreements_out.append(row)
        out["agreements"] = agreements_out
    return out


def _fallback_file_path(
    root: Path,
    bundle_path: str,
    file_name: str,
    fallbacks: Mapping[str, Mapping[str, object]] | None,
) -> Path | None:
    if not fallbacks or not bundle_path or not file_name:
        return None
    spec = fallbacks.get(bundle_path)
    if not isinstance(spec, Mapping):
        return None
    files = spec.get("files")
    if isinstance(files, list) and file_name in files:
        cand = root / release_gates.CAPABILITY_FALLBACKS_DIR / bundle_path / file_name
        if cand.is_file():
            return cand
    return None


def _collect_acc_data_for_bundle(
    root: Path,
    bundle_path: str,
    all_acc_units: dict[str, dict],
    all_acc_positions: dict[str, dict],
    *,
    fallbacks: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[dict[str, dict], dict[str, dict]]:
    merged_units = dict(all_acc_units)
    merged_positions = dict(all_acc_positions)
    acc_path = _find_ancestor_acc_definitions(root, bundle_path)
    if acc_path is not None:
        acc_bundle = acc_path.parent.relative_to(root).as_posix()
        resolved_acc = _fallback_file_path(root, acc_bundle, acc_path.name, fallbacks) or acc_path
        payload = json.loads(resolved_acc.read_text(encoding="utf-8"))
        for unit in payload.get("units", []):
            if isinstance(unit, dict) and unit.get("id"):
                merged_units[str(unit["id"]).strip()] = unit
        for pos in payload.get("positions", []):
            if isinstance(pos, dict) and pos.get("call_sign"):
                merged_positions[str(pos["call_sign"]).strip()] = pos
    return merged_units, merged_positions


def _file_entry(repo_path: str, raw_bytes: bytes, *, requires: list[str] | None = None) -> dict[str, object]:
    entry: dict[str, object] = {
        "repo_path": repo_path,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "size_bytes": len(raw_bytes),
    }
    if requires is not None:
        entry["requires"] = requires
    return entry


_SCHEMA3_DOCUMENT_KINDS = (
    "tma_definitions",
    "tma_layout",
    "tma_coordination",
    "definitions",
    "acc_definitions",
    "acc_layout",
    "acc_coordination",
)
_COORDINATION_KINDS = ("tma_coordination", "acc_coordination")
_ANCESTOR_ACC_FILES = (
    ("acc_definitions.json", "acc_definitions"),
    ("acc_layout.json", "acc_layout"),
    ("acc_coordination.json", "acc_coordination"),
    ("sector_definitions.json", "definitions"),
)


def _source_path(root: Path, repo_path: str) -> Path | None:
    """The file behind an entry's ``repo_path``; an ``airac_variants/`` alias keeps its source."""
    if not repo_path:
        return None
    path = root / repo_path
    if path.is_file():
        return path
    prefix = "airac_variants/"
    if repo_path.startswith(prefix):
        source = root / repo_path[len(prefix):]
        if source.is_file():
            return source
    return None


def _read_document(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else None


def _ancestor_acc_dir(root: Path, bundle_path: str) -> str:
    """The nearest folder with ``acc_definitions.json``, the bundle's own included.

    As the game looks it up: an ACC folder read as a bundle is its own ancestor.
    """
    parts = [part for part in bundle_path.replace("\\", "/").split("/") if part]
    for step in range(8):
        depth = len(parts) - step
        if depth < 1:
            break
        candidate = "/".join(parts[:depth])
        if (root / candidate / "acc_definitions.json").is_file():
            return candidate
    return ""


def coordination_kind(files: object) -> str:
    """Which schema-3 coordination kind this entry carries, "" when it carries none."""
    if not isinstance(files, dict):
        return ""
    for kind in _COORDINATION_KINDS:
        entry = files.get(kind)
        if isinstance(entry, dict) and entry.get("repo_path"):
            return kind
    return ""


def _child_tma_definitions(
    root: Path,
    acc_dir_path: Path,
    *,
    fallbacks: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Every TMA under an ACC folder, whose units and call signs the game knows for its rows."""
    units: list[object] = []
    positions: list[object] = []
    for path in sorted(acc_dir_path.rglob("tma_definitions.json")):
        child_bundle = path.parent.relative_to(root).as_posix()
        resolved = _fallback_file_path(root, child_bundle, path.name, fallbacks) or path
        document = schema3_features.with_every_tier(_read_document(resolved))
        for key, collected in (("units", units), ("positions", positions)):
            values = document.get(key)
            if isinstance(values, list):
                collected.extend(values)
    return {"units": units, "positions": positions}


def _neighbour_acc_documents(
    root: Path, bundle_path: str, own: dict[str, dict], acc: dict[str, dict]
) -> list[dict]:
    """The acc documents of every FIR folder a row end reaches into.

    The released checker resolves an end this bundle and its ancestor ACC do not define by
    the folder its first four letters name (``tma_checker._fir_acc``); the record claims
    exactly those names, so the same helper finds the same documents.
    """
    declared = schema3_features.declared_names(
        own.get("tma_definitions"), own.get("acc_definitions"), acc.get("acc_definitions")
    )
    codes: list[str] = []
    for kind in _COORDINATION_KINDS:
        document = own.get(kind)
        if not isinstance(document, dict):
            continue
        for row in schema3_features.agreement_rows(document):
            for end in schema3_features.agreement_ends(row):
                code = end[:4].upper()
                if end not in declared and code not in codes:
                    codes.append(code)
    documents: list[dict] = []
    for code in codes:
        units, positions = tma_checker._fir_acc(root / bundle_path, code)
        if units or positions:
            documents.append({"units": units, "positions": positions})
    return documents


def bundle_airspace_context(
    root: Path,
    bundle_path: str,
    files: object,
    *,
    fallbacks: Mapping[str, Mapping[str, object]] | None = None,
) -> schema3_features.AirspaceContext:
    """What the bundle's own files and its ancestor ACC folder define."""
    own: dict[str, dict] = {}
    entries = files if isinstance(files, dict) else {}
    for kind in _SCHEMA3_DOCUMENT_KINDS:
        # A full-feed entry of an unmoved bundle keeps the legacy `definitions` and adds the
        # schema-3 one under `definitions_schema3`; the schema-3 documents are the ones read.
        entry = entries.get(f"{kind}_schema3") if kind == "definitions" else None
        entry = entry if isinstance(entry, dict) else entries.get(kind)
        if not isinstance(entry, dict):
            continue
        source = _source_path(root, str(entry.get("repo_path", "")))
        if source is not None:
            source = _fallback_file_path(root, bundle_path, source.name, fallbacks) or source
        document = _read_document(source)
        if document is not None:
            own[kind] = document
    acc: dict[str, dict] = {}
    acc_dir = _ancestor_acc_dir(root, bundle_path)
    if acc_dir and acc_dir != bundle_path.strip("/"):
        for file_name, kind in _ANCESTOR_ACC_FILES:
            acc_source = _fallback_file_path(root, acc_dir, file_name, fallbacks) or (root / acc_dir / file_name)
            document = _read_document(acc_source)
            if document is not None:
                acc[kind] = document
    # The game checks an ACC's own coordination with every child TMA's units and call signs
    # handed to it, so a row that ends at one of them is valid there.
    if coordination_kind(files) == "acc_coordination" and acc_dir:
        own["tma_definitions"] = _child_tma_definitions(root, root / acc_dir, fallbacks=fallbacks)
    return schema3_features.airspace_context(
        own,
        acc,
        bundle=bundle_path,
        neighbour_documents=_neighbour_acc_documents(root, bundle_path, own, acc),
    )


def coordination_variant(
    root: Path,
    bundle_path: str,
    files: object,
    *,
    fallbacks: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[tuple[str, ...], dict | None, bytes | None]:
    """(capabilities the coordination uses, its downgraded document, its authored bytes)."""
    kind = coordination_kind(files)
    if not kind:
        return (), None, None
    entry = files.get(kind) if isinstance(files, dict) else None
    source = _source_path(root, str(entry.get("repo_path", "")) if isinstance(entry, dict) else "")
    if source is not None:
        source = _fallback_file_path(root, bundle_path, source.name, fallbacks) or source
    document = _read_document(source)
    if document is None or source is None:
        return (), None, None
    context = bundle_airspace_context(root, bundle_path, files, fallbacks=fallbacks)
    capabilities = schema3_features.used_capabilities(
        schema3_features.agreement_rows(document), context
    )
    if not capabilities:
        return capabilities, None, None
    # An AIRAC document keeps its resolved copy at the bundle path (the projection writes it
    # there) and its downgraded copy, every tier downgraded, at the ``airac_variants/`` alias:
    # the authored copy has its own path, so nothing is refused.
    return capabilities, schema3_features.downgrade_document(document, context), _canonical_lf(
        source.read_bytes()
    )


def _feature_variant_path(repo_path: str) -> str:
    """The archive path of a gated bundle's authored copy.

    The game installs ``feature_variants/<bundle>/<file>`` at ``airac_variants/<bundle>/<file>``,
    the folder the bundle's own readers open, so the authored rows reach them without taking
    the path a build without the capability reads its downgraded copy from.
    """
    prefix = "airac_variants/"
    original = repo_path[len(prefix):] if repo_path.startswith(prefix) else repo_path
    return "feature_variants/" + original


def _repathed(fentry: dict, repo_path: str, raw_bytes: bytes) -> dict:
    entry = dict(fentry)
    entry["repo_path"] = repo_path
    entry["sha256"], entry["size_bytes"] = _file_meta(raw_bytes)
    return entry


def _schema3_entries(
    s3_entry: dict,
    schema3_files: dict,
    variant: tuple[tuple[str, ...], dict | None, bytes | None],
    generated: dict[str, bytes],
    archive_sources: dict[str, str],
) -> list[dict]:
    """Today's entry, or the downgraded one and then the authored one a capable build takes."""
    capabilities, downgraded, authored = variant
    kind = coordination_kind(schema3_files)
    if not kind:
        return [s3_entry]
    today = str(schema3_files[kind]["repo_path"])
    if not capabilities or downgraded is None or authored is None:
        return [s3_entry]

    downgraded_bytes = (json.dumps(downgraded, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    # The downgraded copy keeps today's path and the authored one takes a third prefix, so no
    # two documents ever reach one archive path.
    authored_path = _feature_variant_path(today)

    downgraded_files = dict(schema3_files)
    downgraded_files[kind] = _repathed(schema3_files[kind], today, downgraded_bytes)
    authored_files = dict(schema3_files)
    authored_files[kind] = _repathed(schema3_files[kind], authored_path, authored)
    generated[today] = downgraded_bytes
    archive_sources[today] = today
    generated[authored_path] = authored
    archive_sources[authored_path] = authored_path
    requires = list(s3_entry.get("requires", [])) if isinstance(s3_entry.get("requires"), list) else []
    return [
        {**s3_entry, "files": downgraded_files},
        {**s3_entry, "files": authored_files, "requires": sorted(set(requires) | set(capabilities))},
    ]


def _schema3_bundle_entries(
    root: Path,
    bundle_path: str,
    s3_entry: dict,
    schema3_files: dict,
    source_files: dict,
    generated: dict[str, bytes],
    archive_sources: dict[str, str],
    fallbacks: Mapping[str, Mapping[str, object]],
) -> list[dict]:
    """Emit schema-3 entries, splitting fallback copies from ``release/capability_fallbacks/`` if present."""
    fb_spec = fallbacks.get(bundle_path)
    if not isinstance(fb_spec, Mapping):
        return _schema3_entries(
            s3_entry,
            schema3_files,
            coordination_variant(root, bundle_path, source_files),
            generated,
            archive_sources,
        )

    fb_files_set = {str(name) for name in (fb_spec.get("files") or [])}  # type: ignore[union-attr]
    fb_reqs = [str(name) for name in (fb_spec.get("requires") or [])]  # type: ignore[union-attr]
    coord_kind = coordination_kind(schema3_files)

    fallback_files: dict[str, object] = {}
    for fkind, fentry in schema3_files.items():
        if not isinstance(fentry, dict) or not fentry.get("repo_path"):
            fallback_files[fkind] = fentry
            continue
        rp = str(fentry["repo_path"])
        orig = rp[len("airac_variants/") :] if rp.startswith("airac_variants/") else rp
        fb_path = _fallback_file_path(root, bundle_path, Path(orig).name, fallbacks)
        if fb_path is not None:
            fb_bytes = _canonical_lf(fb_path.read_bytes())
            fallback_files[fkind] = _repathed(fentry, rp, fb_bytes)
            generated[rp] = fb_bytes
            archive_sources[rp] = rp
        else:
            fallback_files[fkind] = fentry

    fb_caps, fb_downgraded, _ = coordination_variant(
        root, bundle_path, source_files, fallbacks=fallbacks
    )
    if coord_kind and fb_caps and fb_downgraded is not None:
        dg_bytes = (json.dumps(fb_downgraded, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        coord_entry = fallback_files[coord_kind]
        assert isinstance(coord_entry, dict)
        coord_rp = str(coord_entry["repo_path"])
        fallback_files[coord_kind] = _repathed(coord_entry, coord_rp, dg_bytes)
        generated[coord_rp] = dg_bytes
        archive_sources[coord_rp] = coord_rp

    authored_caps, _authored_downgraded, _authored_bytes = coordination_variant(
        root, bundle_path, source_files
    )
    authored_files: dict[str, object] = {}
    for fkind, fentry in schema3_files.items():
        if not isinstance(fentry, dict) or not fentry.get("repo_path"):
            authored_files[fkind] = fentry
            continue
        rp = str(fentry["repo_path"])
        orig = rp[len("airac_variants/") :] if rp.startswith("airac_variants/") else rp
        fname = Path(orig).name
        if fname in fb_files_set or (fkind == coord_kind and authored_caps):
            disk_bytes = _canonical_lf((root / orig).read_bytes())
            feat_rp = _feature_variant_path(rp)
            authored_files[fkind] = _repathed(fentry, feat_rp, disk_bytes)
            generated[feat_rp] = disk_bytes
            archive_sources[feat_rp] = feat_rp
        else:
            authored_files[fkind] = fallback_files[fkind]

    base_reqs = list(s3_entry.get("requires", [])) if isinstance(s3_entry.get("requires"), list) else []
    return [
        {**s3_entry, "files": fallback_files},
        {
            **s3_entry,
            "files": authored_files,
            "requires": sorted(set(base_reqs) | set(fb_reqs) | set(authored_caps)),
        },
    ]


def _frozen_bundle_files(
    root: Path,
    bundle_path: str,
    index_entry: dict[str, object] | None,
) -> dict[str, bytes] | None:
    """Return a bundle's frozen legacy bytes when its snapshot is complete, else None."""
    if not isinstance(index_entry, dict):
        return None

    frozen_list = index_entry.get("frozen_files")
    if not isinstance(frozen_list, list):
        return None
    frozen_set = {str(name) for name in frozen_list}
    required = {"sector_configs.json", "sector_influence.json", "sector_definitions.json"}
    if not required <= frozen_set:
        return None

    frozen_rel_dir = legacy_path_for_bundle(bundle_path, index_entry)
    frozen_dir = root / FROZEN_DIR / frozen_rel_dir
    loaded: dict[str, bytes] = {}
    for fname in sorted(frozen_set):
        fpath = frozen_dir / fname
        if not fpath.is_file():
            return None
        loaded[fname] = _canonical_lf(fpath.read_bytes())
    return loaded


def _tma_position_ids(tma_defs: dict[str, object], tma_layout: dict[str, object] | None = None) -> list[str]:
    pos_ids: list[str] = []
    if tma_layout is not None:
        radar_layouts, _ = _schema3_layouts(tma_defs, tma_layout)
        for layout in radar_layouts:
            for pos in layout.get("positions", []) or []:
                sid = str(pos.get("sector", "")).strip()
                if sid and sid not in pos_ids:
                    pos_ids.append(sid)
        return pos_ids
    for layout in tma_defs.get("layouts", []) or []:  # type: ignore[union-attr]
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
    raw_rows = doc.get("volumes") if "volumes" in doc else doc.get("sector_definitions")
    out: dict[str, object] = {}
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
                    item[k] = deepcopy(v)
            if "sector_id" not in item:
                item["sector_id"] = sector_id
            new_rows.append(item)
        out["sector_definitions"] = new_rows
    if isinstance(doc.get("airac_overrides"), dict):
        overrides: dict[str, object] = {}
        for tier, tier_doc in doc["airac_overrides"].items():  # type: ignore[union-attr]
            if isinstance(tier_doc, dict):
                overrides[tier] = _convert_definitions_doc(tier_doc, all_pos_ids, aliases)
            else:
                overrides[tier] = tier_doc
        out["airac_overrides"] = overrides
    return out


def project_sector_definitions(
    definitions_doc: dict[str, object],
    tma_defs: dict[str, object],
    tma_layout: dict[str, object] | None = None,
    *,
    sector_aliases: dict[str, list[str]] | None = None,
) -> bytes:
    """Project schema-3 sector_definitions.json back to scalar legacy sector_id rows."""
    all_pos_ids = _tma_position_ids(tma_defs, tma_layout)
    converted = _convert_definitions_doc(definitions_doc, all_pos_ids, sector_aliases or {})
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _convert_with_airac_overrides(doc: dict[str, object], convert_single) -> dict[str, object]:
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
        if k == "schema":
            continue
        if k == "airports" and "airport" not in doc:
            if isinstance(v, list) and len(v) == 1:
                out["airport"] = v[0]
            else:
                out["airport"] = deepcopy(v)
        else:
            out[k] = deepcopy(v)
    return out


def _convert_colors_or_style_single(doc: dict[str, object]) -> dict[str, object]:
    return {k: deepcopy(v) for k, v in doc.items() if k != "schema"}


def project_mva_payload(doc: dict[str, object]) -> bytes:
    converted = _convert_with_airac_overrides(doc, _convert_mva_single)
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def project_runway_configs_payload(doc: dict[str, object]) -> bytes:
    converted = _convert_with_airac_overrides(doc, _convert_colors_or_style_single)
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
    out = {k: deepcopy(v) for k, v in ds.items() if k != "schema"}
    item_cfgs: list[list[object]] = []
    all_items_have_cfg = True
    item_count = 0
    for section in ("line_sections", "filled_polygons", "labels"):
        rows = out.get(section)
        if isinstance(rows, list):
            converted_rows = [_convert_misc_row(row) if isinstance(row, dict) else row for row in rows]
            out[section] = converted_rows
            for r in converted_rows:
                if isinstance(r, dict):
                    item_count += 1
                    cfgs = r.get("configs")
                    if isinstance(cfgs, list) and cfgs:
                        item_cfgs.append(cfgs)
                    else:
                        all_items_have_cfg = False
    if (
        "runway_config" not in out
        and item_count > 0
        and all_items_have_cfg
        and len(item_cfgs) == item_count
        and all(c == item_cfgs[0] for c in item_cfgs)
    ):
        shared = item_cfgs[0]
        out["runway_config"] = shared[0] if len(shared) == 1 else list(shared)
        for section in ("line_sections", "filled_polygons", "labels"):
            rows = out.get(section)
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict):
                        r.pop("configs", None)
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
    converted = _convert_with_airac_overrides(doc, _convert_misc_single)
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _convert_alt_speed_to_legacy_constraint(spec: dict, unit_suffix: str) -> dict:
    if unit_suffix == "ft":
        if "at_ft" in spec:
            return {"type": "at", "ft": spec["at_ft"]}
        if "at_or_above_ft" in spec and "at_or_below_ft" in spec:
            return {"type": "between", "min_ft": spec["at_or_above_ft"], "max_ft": spec["at_or_below_ft"]}
        if "at_or_above_ft" in spec:
            return {"type": "at_or_above", "ft": spec["at_or_above_ft"]}
        if "at_or_below_ft" in spec:
            return {"type": "at_or_below", "ft": spec["at_or_below_ft"]}
    else:
        if "at_kt" in spec:
            return {"type": "at", "kt": spec["at_kt"]}
        if "at_or_above_kt" in spec and "at_or_below_kt" in spec:
            return {"type": "between", "min_kt": spec["at_or_above_kt"], "max_kt": spec["at_or_below_kt"]}
        if "at_or_above_kt" in spec:
            return {"type": "at_or_above", "kt": spec["at_or_above_kt"]}
        if "at_or_below_kt" in spec:
            return {"type": "at_or_below", "kt": spec["at_or_below_kt"]}
    return deepcopy(spec)


def _convert_constraints_single(doc: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in doc.items():
        if k == "schema":
            continue
        if k in ("sids", "stars", "approaches", "iaps") and isinstance(v, dict):
            dst_key = "iaps" if k == "approaches" else k
            bucket_out: dict[str, object] = {}
            for proc_id, fixes in v.items():
                if not isinstance(fixes, dict):
                    bucket_out[proc_id] = deepcopy(fixes)
                    continue
                fixes_out: dict[str, object] = {}
                for fix_id, rule in fixes.items():
                    if not isinstance(rule, dict):
                        fixes_out[fix_id] = deepcopy(rule)
                        continue
                    r_out: dict[str, object] = {}
                    if isinstance(rule.get("altitude"), dict):
                        r_out["altitude"] = _convert_alt_speed_to_legacy_constraint(rule["altitude"], "ft")
                    if isinstance(rule.get("speed"), dict):
                        r_out["speed"] = _convert_alt_speed_to_legacy_constraint(rule["speed"], "kt")
                    fixes_out[fix_id] = r_out
                bucket_out[proc_id] = fixes_out
            out[dst_key] = bucket_out
        else:
            out[k] = deepcopy(v)
    return out


def project_constraints_payload(doc: dict[str, object]) -> bytes:
    converted = _convert_with_airac_overrides(doc, _convert_constraints_single)
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _convert_climb_leg_to_legacy(leg: dict) -> dict:
    out: dict[str, object] = {}
    leg_type = str(leg.get("type", "")).strip()
    out["path_term"] = _LEG_TYPE_TO_TERM.get(leg_type, leg_type.upper())
    for k in ("ident", "course", "turn_direction", "distance_nm", "recommended_navaid", "endpoint"):
        if k in leg and leg[k] is not None:
            out[k] = deepcopy(leg[k])
    if isinstance(leg.get("altitude"), dict):
        alt = leg["altitude"]
        if "at_or_above_ft" in alt and "at_or_below_ft" in alt:
            out["altitude_description"] = "B"
            out["altitude1"] = alt["at_or_above_ft"]
            out["altitude2"] = alt["at_or_below_ft"]
        elif "at_or_above_ft" in alt:
            out["altitude_description"] = "+"
            out["altitude1"] = alt["at_or_above_ft"]
        elif "at_or_below_ft" in alt:
            out["altitude_description"] = "-"
            out["altitude1"] = alt["at_or_below_ft"]
        elif "at_ft" in alt:
            out["altitude_description"] = "@"
            out["altitude1"] = alt["at_ft"]
    if isinstance(leg.get("speed"), dict) and "at_or_below_kt" in leg["speed"]:
        out["speed_limit"] = leg["speed"]["at_or_below_kt"]
    if isinstance(leg.get("crossing"), dict):
        cr = leg["crossing"]
        c_out: dict[str, object] = {}
        if "id" in cr:
            c_out["id"] = cr["id"]
        if "first_of" in cr:
            c_out["first_of"] = deepcopy(cr["first_of"])
        if isinstance(cr.get("altitude"), dict):
            alt = cr["altitude"]
            if "at_or_above_ft" in alt and "at_or_below_ft" in alt:
                c_out["altitude1"] = alt["at_or_above_ft"]
                c_out["altitude2"] = alt["at_or_below_ft"]
            elif "at_or_above_ft" in alt:
                c_out["altitude1"] = alt["at_or_above_ft"]
            elif "at_ft" in alt:
                c_out["altitude1"] = alt["at_ft"]
        out["crossing"] = c_out
    if "containment" in leg:
        out["containment"] = deepcopy(leg["containment"])
    return out


def _apply_use_entry_to_slot(slot: dict, row: dict, *, allow_aircraft_types: bool) -> None:
    if "spawn" in row:
        slot["spawn_enabled"] = bool(row["spawn"])
    if "join_from" in row:
        slot["join_from"] = deepcopy(row["join_from"])
    if allow_aircraft_types:
        aircraft = row.get("aircraft")
        if isinstance(aircraft, dict) and isinstance(aircraft.get("only"), dict) and aircraft["only"].get("types"):
            slot["aircraft_types"] = deepcopy(aircraft["only"]["types"])
        elif isinstance(row.get("only_for"), dict) and row["only_for"].get("types"):
            slot["aircraft_types"] = deepcopy(row["only_for"]["types"])


def _merge_proc_single_docs(
    use_doc: dict | None,
    climb_doc: dict | None,
    dep_doc: dict | None,
    *,
    airport: str,
) -> dict[str, object]:
    out: dict[str, object] = {"airport": airport}
    for d in (use_doc, climb_doc, dep_doc):
        if isinstance(d, dict) and "airac_min" in d and "airac_min" not in out:
            out["airac_min"] = d["airac_min"]

    defaults: dict[str, object] = {}
    if isinstance(climb_doc, dict) and "initial_climb_ft" in climb_doc:
        defaults["init_climb"] = climb_doc["initial_climb_ft"]

    # Process procedure_use rows into defaults / stars / sids / iaps / transitions / configs / runways
    if isinstance(use_doc, dict):
        for row in use_doc.get("use", []) or []:
            if not isinstance(row, dict):
                continue
            rwys = row.get("runways") or []
            cfgs = row.get("configs") or []
            targets: list[tuple[dict, bool]] = []
            if not rwys and not cfgs:
                targets.append((out, True))
            else:
                for r in rwys:
                    r_map = out.setdefault("runways", {}).setdefault(str(r), {})  # type: ignore[union-attr]
                    targets.append((r_map, False))
                for c in cfgs:
                    c_map = out.setdefault("configs", {}).setdefault(str(c), {})  # type: ignore[union-attr]
                    targets.append((c_map, False))
            for host, is_root in targets:
                if row.get("kind") == "all":
                    if is_root and "spawn" in row:
                        defaults["spawn_enabled"] = bool(row["spawn"])
                    elif not is_root and "spawn" in row:
                        # Blanket per-runway/config spawn rule applies across buckets
                        host.setdefault("sids", {})
                        if isinstance(host["sids"], dict):
                            pass
                    continue
                if row.get("kind") == "transitions":
                    trans = host.setdefault("transitions", {})
                    if "spawn" in row:
                        trans["spawn_enabled"] = bool(row["spawn"])
                    continue
                for bkey in ("sids", "stars", "approaches", "transitions"):
                    idents = row.get(bkey)
                    if not isinstance(idents, list) or not idents:
                        continue
                    dst_bucket = "iaps" if bkey == "approaches" else bkey
                    bucket = host.setdefault(dst_bucket, {})
                    for ident in idents:
                        slot = bucket.setdefault(str(ident), {})
                        _apply_use_entry_to_slot(
                            slot, row, allow_aircraft_types=(is_root and dst_bucket == "sids")
                        )

    if defaults:
        out["defaults"] = defaults

    # Process initial_climb exceptions
    if isinstance(climb_doc, dict):
        for ex in climb_doc.get("exceptions", []) or []:
            if not isinstance(ex, dict) or "initial_climb_ft" not in ex:
                continue
            ic = ex["initial_climb_ft"]
            rwys = ex.get("runways") or []
            cfgs = ex.get("configs") or []
            sids = ex.get("sids") or []
            if not rwys and not cfgs:
                for sid in sids:
                    slot = out.setdefault("sids", {}).setdefault(str(sid), {})  # type: ignore[union-attr]
                    slot["init_climb"] = ic
            else:
                for r in rwys:
                    rm = out.setdefault("runways", {}).setdefault(str(r), {})  # type: ignore[union-attr]
                    if sids:
                        for sid in sids:
                            rm.setdefault("sids", {}).setdefault(str(sid), {})["init_climb"] = ic
                    else:
                        rm["init_climb"] = ic
                for c in cfgs:
                    cm = out.setdefault("configs", {}).setdefault(str(c), {})  # type: ignore[union-attr]
                    if sids:
                        for sid in sids:
                            cm.setdefault("sids", {}).setdefault(str(sid), {})["init_climb"] = ic
                    else:
                        cm["init_climb"] = ic

    # Process departure_variants
    if isinstance(dep_doc, dict) and isinstance(dep_doc.get("sids"), dict):
        for sid_id, s_entry in dep_doc["sids"].items():
            if not isinstance(s_entry, dict):
                continue
            variants = s_entry.get("variants", [])
            converted_vars = []
            for v in variants:
                if not isinstance(v, dict):
                    continue
                v_out: dict[str, object] = {"id": v["id"]}
                for k in ("display_name", "runways", "auto_rule"):
                    if k in v:
                        v_out[k] = deepcopy(v[k])
                v_out["legs"] = [_convert_climb_leg_to_legacy(leg) for leg in v.get("legs", [])]
                converted_vars.append(v_out)
            slot = out.setdefault("sids", {}).setdefault(str(sid_id), {})  # type: ignore[union-attr]
            slot["climb_variants"] = converted_vars

    return out


def project_procedure_options_payload(
    use_doc: dict[str, object] | None,
    climb_doc: dict[str, object] | None = None,
    dep_doc: dict[str, object] | None = None,
) -> bytes:
    """Reconstruct legacy procedure_options.json bytes from schema-3 procedure files."""
    if isinstance(use_doc, dict) and use_doc.get("schema") != 3 and climb_doc is None and dep_doc is None:
        # Legacy/schema-2 dict caller
        converted = _convert_with_airac_overrides(use_doc, lambda d: d)
        return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    airport = ""
    for d in (use_doc, climb_doc, dep_doc):
        if isinstance(d, dict) and d.get("airport"):
            airport = str(d["airport"]).strip().upper()
            break
    base = _merge_proc_single_docs(
        _resolve_default_doc(use_doc) if use_doc else None,
        _resolve_default_doc(climb_doc) if climb_doc else None,
        _resolve_default_doc(dep_doc) if dep_doc else None,
        airport=airport,
    )
    overrides: dict[str, object] = {}
    for tier in airac_overrides.TIERS:
        u_t = (use_doc or {}).get("airac_overrides", {}).get(tier) if isinstance((use_doc or {}).get("airac_overrides"), dict) else None
        c_t = (climb_doc or {}).get("airac_overrides", {}).get(tier) if isinstance((climb_doc or {}).get("airac_overrides"), dict) else None
        v_t = (dep_doc or {}).get("airac_overrides", {}).get(tier) if isinstance((dep_doc or {}).get("airac_overrides"), dict) else None
        if u_t or c_t or v_t:
            overrides[tier] = _merge_proc_single_docs(u_t, c_t, v_t, airport=airport)
    if overrides:
        base["airac_overrides"] = overrides
    return (json.dumps(base, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


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
    airport: str = "",
    unit_aliases: dict[str, str] | None = None,
) -> dict[str, object]:
    out: dict[str, object] = {}
    if airport and "airport" not in doc:
        out["airport"] = airport
    for k, v in doc.items():
        if k == "schema":
            out["schema"] = 1
        else:
            out[k] = deepcopy(v)
    if "schema" not in out:
        out["schema"] = 1
    positions = out.get("positions")
    if isinstance(positions, dict):
        aliases = {
            str(k).strip().upper(): str(v).strip()
            for k, v in (unit_aliases if unit_aliases is not None else CANONICAL_TO_LEGACY_UNIT_ALIASES).items()
            if str(k).strip() and str(v).strip()
        }
        rewritten: dict[str, object] = {}
        for raw_key, block in positions.items():
            upper = str(raw_key).strip().upper()
            rewritten[aliases.get(upper, str(raw_key))] = block
        out["positions"] = rewritten
    return out


def project_map_display_payload(
    doc: dict[str, object],
    *,
    airport: str = "",
    unit_aliases: dict[str, str] | None = None,
) -> bytes:
    converted = _convert_with_airac_overrides(
        doc, lambda d: _convert_map_display_single(d, airport=airport, unit_aliases=unit_aliases)
    )
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _lookup_frozen_file_entry(
    root: Path,
    repo_path: str,
    kind: str,
    files_index: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    norm = repo_path.replace("\\", "/")
    meta = files_index.get(norm)
    if isinstance(meta, dict) and meta.get("kind") == kind:
        return meta
    for _leg_path, cand in files_index.items():
        if cand.get("kind") == kind and norm in (cand.get("sources") or {}):
            return cand
    return None


def _frozen_file_matches_sources(root: Path, meta: dict[str, object]) -> bytes | None:
    sources = meta.get("sources")
    if not isinstance(sources, dict):
        return None
    for src_rel, expected_sha in sources.items():
        src_path = root / str(src_rel)
        if not src_path.is_file() or _sha256_file(src_path) != str(expected_sha):
            return None
    frozen_rel = str(meta.get("frozen_file", ""))
    frozen_path = root / FROZEN_DIR / frozen_rel
    if frozen_rel and frozen_path.is_file():
        return _canonical_lf(frozen_path.read_bytes())
    return None


def _legacy_visual_constraint(spec: dict, value_key: str) -> dict[str, object]:
    recommended = bool(spec.get("recommended", False))
    status = "recommended" if recommended else "required"
    if value_key == "value_ft":
        if "at_or_above_ft" in spec and "at_or_below_ft" in spec:
            return {
                "value_ft": spec["at_or_above_ft"],
                "value2_ft": spec["at_or_below_ft"],
                "status": status,
                "kind": "between",
            }
        if "at_or_above_ft" in spec:
            return {"value_ft": spec["at_or_above_ft"], "status": status, "kind": "at_or_above"}
        if "at_or_below_ft" in spec:
            return {"value_ft": spec["at_or_below_ft"], "status": status, "kind": "at_or_below"}
        return {"value_ft": spec["at_ft"], "status": status, "kind": "at"}
    if "at_or_above_kt" in spec:
        return {"value_kt": spec["at_or_above_kt"], "status": status, "kind": "at_or_above"}
    if "at_or_below_kt" in spec:
        return {"value_kt": spec["at_or_below_kt"], "status": status, "kind": "at_or_below"}
    return {"value_kt": spec["at_kt"], "status": status, "kind": "at"}


def _convert_visual_approaches_single(
    doc: dict[str, object],
) -> tuple[dict[str, object], dict[str, object] | None, dict[str, object] | None]:
    airport = str(doc.get("airport", "")).strip().upper()
    procs_out: list[dict[str, object]] = []
    go_arounds_out: list[dict[str, object]] = []
    sight_variants_out: list[dict[str, object]] = []
    for raw_proc in doc.get("procedures", []) or []:  # type: ignore[union-attr]
        if not isinstance(raw_proc, dict):
            continue
        p_out: dict[str, object] = {}
        for k in ("id", "name", "aliases", "classification", "policy_profile", "source"):
            if k in raw_proc:
                p_out[k] = deepcopy(raw_proc[k])
        vars_out: list[dict[str, object]] = []
        for raw_var in raw_proc.get("variants", []) or []:
            if not isinstance(raw_var, dict):
                continue
            v_out: dict[str, object] = {}
            for k in ("id", "runway", "clearance_name", "entry_point_id", "sight_reference_point_id",
                      "join_policy", "sight_reference", "final"):
                if k in raw_var:
                    v_out[k] = deepcopy(raw_var[k])
            legs_out: list[dict[str, object]] = []
            for raw_leg in raw_var.get("legs", []) or []:
                if not isinstance(raw_leg, dict):
                    continue
                l_out: dict[str, object] = {
                    "id": raw_leg["id"],
                    "name": raw_leg["name"],
                    "path_term": _LEG_TYPE_TO_TERM.get(str(raw_leg.get("type", "")), str(raw_leg.get("type", "")).upper()),
                }
                pt = raw_leg.get("point")
                if isinstance(pt, list) and len(pt) >= 2:
                    l_out["latitude"] = pt[0]
                    l_out["longitude"] = pt[1]
                if "fly_over" in raw_leg:
                    l_out["fly_over"] = raw_leg["fly_over"]
                for k in ("course_deg", "reference", "arc_radius_nm", "turn_direction"):
                    if k in raw_leg:
                        l_out[k] = deepcopy(raw_leg[k])
                if isinstance(raw_leg.get("arc_center"), list) and len(raw_leg["arc_center"]) >= 2:
                    l_out["arc_center"] = {"latitude": raw_leg["arc_center"][0], "longitude": raw_leg["arc_center"][1]}
                if isinstance(raw_leg.get("altitude"), dict):
                    l_out["altitude"] = _legacy_visual_constraint(raw_leg["altitude"], "value_ft")
                if isinstance(raw_leg.get("speed"), dict):
                    l_out["speed"] = _legacy_visual_constraint(raw_leg["speed"], "value_kt")
                legs_out.append(l_out)
            v_out["legs"] = legs_out
            vars_out.append(v_out)

            ga = raw_var.get("go_around")
            if isinstance(ga, dict):
                ga_legs: list[dict[str, object]] = []
                for gleg in ga.get("legs", []) or []:
                    if not isinstance(gleg, dict):
                        continue
                    gl_out: dict[str, object] = {
                        "sequence": gleg["sequence"],
                        "path_term": _LEG_TYPE_TO_TERM.get(str(gleg.get("type", "")), str(gleg.get("type", "")).upper()),
                    }
                    for k in ("ident", "course", "turn_direction", "distance", "description",
                              "recommended_navaid", "theta", "rho", "arc_center_ident"):
                        if k in gleg:
                            gl_out[k] = deepcopy(gleg[k])
                    if isinstance(gleg.get("point"), list) and len(gleg["point"]) >= 2:
                        gl_out["latitude"] = gleg["point"][0]
                        gl_out["longitude"] = gleg["point"][1]
                    if isinstance(gleg.get("recommended_navaid_point"), list) and len(gleg["recommended_navaid_point"]) >= 2:
                        gl_out["recommended_navaid_latitude"] = gleg["recommended_navaid_point"][0]
                        gl_out["recommended_navaid_longitude"] = gleg["recommended_navaid_point"][1]
                    if isinstance(gleg.get("arc_center_point"), list) and len(gleg["arc_center_point"]) >= 2:
                        gl_out["arc_center_latitude"] = gleg["arc_center_point"][0]
                        gl_out["arc_center_longitude"] = gleg["arc_center_point"][1]
                    if isinstance(gleg.get("altitude"), dict):
                        alt = gleg["altitude"]
                        if "at_or_above_ft" in alt and "at_or_below_ft" in alt:
                            gl_out["altitude1"], gl_out["altitude2"], gl_out["altitude_desc"] = alt["at_or_above_ft"], alt["at_or_below_ft"], "B"
                        elif "at_or_above_ft" in alt:
                            gl_out["altitude1"], gl_out["altitude_desc"] = alt["at_or_above_ft"], "+"
                        elif "at_or_below_ft" in alt:
                            gl_out["altitude1"], gl_out["altitude_desc"] = alt["at_or_below_ft"], "-"
                        elif "at_ft" in alt:
                            gl_out["altitude1"], gl_out["altitude_desc"] = alt["at_ft"], "@"
                    if isinstance(gleg.get("speed"), dict) and "at_or_below_kt" in gleg["speed"]:
                        gl_out["speed_limit"] = gleg["speed"]["at_or_below_kt"]
                    ga_legs.append(gl_out)
                go_arounds_out.append({
                    "procedure_id": raw_proc["id"],
                    "variant_id": raw_var["id"],
                    "runway": raw_var["runway"],
                    "source": deepcopy(ga["source"]),
                    "terminal_policy": ga["terminal_policy"],
                    "legs": ga_legs,
                })

            srs = raw_var.get("sight_references")
            if isinstance(srs, dict):
                refs_out: list[dict[str, object]] = []
                for r in srs.get("references", []) or []:
                    if not isinstance(r, dict):
                        continue
                    geom = deepcopy(r.get("geometry", {}))
                    if isinstance(geom, dict):
                        if "point" in geom and isinstance(geom["point"], list) and len(geom["point"]) >= 2:
                            pt_val = geom.pop("point")
                            geom["latitude"] = pt_val[0]
                            geom["longitude"] = pt_val[1]
                        if "points" in geom and isinstance(geom["points"], list):
                            geom["points"] = [
                                {"latitude": p[0], "longitude": p[1]} if isinstance(p, list) and len(p) >= 2 else p
                                for p in geom["points"]
                            ]
                    refs_out.append({
                        "id": r["id"],
                        "name": r["name"],
                        "aliases": deepcopy(r.get("aliases", [])),
                        "geometry": geom,
                        "source": deepcopy(r["source"]),
                    })
                sight_variants_out.append({
                    "procedure_id": raw_proc["id"],
                    "variant_id": raw_var["id"],
                    "default_reference_id": srs["default_reference_id"],
                    "references": refs_out,
                })
        p_out["variants"] = vars_out
        procs_out.append(p_out)

    vis_doc = {"schema_version": 1, "airport": airport, "procedures": procs_out}
    ga_doc = {"schema_version": 1, "airport": airport, "go_arounds": go_arounds_out} if go_arounds_out else None
    sr_doc = {"schema_version": 1, "airport": airport, "variants": sight_variants_out} if sight_variants_out else None
    return vis_doc, ga_doc, sr_doc


def project_visual_procedures_payload(doc: dict[str, object]) -> bytes:
    converted = _convert_with_airac_overrides(doc, lambda d: _convert_visual_approaches_single(d)[0])
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def project_visual_go_arounds_payload(doc: dict[str, object]) -> bytes | None:
    single_ga = _convert_visual_approaches_single(doc)[1]
    if single_ga is None:
        return None
    converted = _convert_with_airac_overrides(doc, lambda d: _convert_visual_approaches_single(d)[1] or {})
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def project_visual_sight_references_payload(doc: dict[str, object]) -> bytes | None:
    single_sr = _convert_visual_approaches_single(doc)[2]
    if single_sr is None:
        return None
    converted = _convert_with_airac_overrides(doc, lambda d: _convert_visual_approaches_single(d)[2] or {})
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def project_legacy_file_bytes(
    root: Path,
    repo_path: str,
    kind: str,
    *,
    force_generate: bool = False,
    files_index: dict[str, dict[str, object]] | None = None,
) -> bytes:
    """Return frozen legacy bytes when schema-3 sources match index.json, else generate."""
    index = load_frozen_files_index(root) if files_index is None else files_index
    meta = _lookup_frozen_file_entry(root, repo_path, kind, index)
    if not force_generate and isinstance(meta, dict):
        frozen_bytes = _frozen_file_matches_sources(root, meta)
        if frozen_bytes is not None:
            return frozen_bytes

    norm = repo_path.replace("\\", "/")
    if norm.startswith(".voiceatc/defaults/"):
        norm = norm[len(".voiceatc/defaults/") :]
    # Always allow legacy_only frozen files (removed skinned colors/style) to serve frozen bytes
    if isinstance(meta, dict) and meta.get("legacy_only"):
        frozen_rel = str(meta.get("frozen_file", ""))
        frozen_path = root / FROZEN_DIR / frozen_rel
        if frozen_rel and frozen_path.is_file():
            return _canonical_lf(frozen_path.read_bytes())

    if kind == "procedure_options":
        return project_procedure_options_default_bytes(
            root, norm, force_generate=force_generate, files_index=index
        )
    if kind == "map_display":
        return project_map_display_default_bytes(
            root, norm, force_generate=force_generate, files_index=index
        )

    # Locate schema-3 source path (preferring an already-stripped .voiceatc/defaults/ file when present)
    src_path = root / repo_path.replace("\\", "/")
    if not src_path.is_file():
        src_path = root / norm
    if not src_path.is_file() and isinstance(meta, dict) and meta.get("sources"):
        src_rel = next(iter(meta["sources"]))
        src_path = root / str(src_rel)
    elif not src_path.is_file():
        if kind in ("visual_procedures", "visual_go_arounds", "visual_sight_references"):
            va_cand = src_path.with_name("visual_approaches.json")
            if va_cand.is_file():
                src_path = va_cand
        for old_p, new_p in _BUNDLE_PATH_TO_LEGACY.items():
            # reverse check: legacy path uses new_p
            if norm.startswith(new_p + "/"):
                cand = root / (old_p + norm[len(new_p):])
                if cand.is_file():
                    src_path = cand
                    break

    raw_bytes = _canonical_lf(src_path.read_bytes())
    doc = json.loads(raw_bytes.decode("utf-8"))
    if kind == "mva":
        return project_mva_payload(doc)
    if kind == "runway_configs":
        return project_runway_configs_payload(doc)
    if kind == "misc_drawings":
        return project_misc_drawings_payload(doc)
    if kind == "constraints":
        return project_constraints_payload(doc)
    if kind == "visual_procedures":
        return project_visual_procedures_payload(doc)
    if kind == "visual_go_arounds":
        return project_visual_go_arounds_payload(doc) or b""
    if kind == "visual_sight_references":
        return project_visual_sight_references_payload(doc) or b""
    if kind in ("colors", "style"):
        converted = _convert_colors_or_style_single(doc)
        return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return raw_bytes


def project_map_display_default_bytes(
    root: Path,
    repo_path: str,
    *,
    force_generate: bool = False,
    files_index: dict[str, dict[str, object]] | None = None,
) -> bytes:
    """Return default-feed legacy map_display.json bytes (airac_overrides stripped, old unit IDs)."""
    index = load_frozen_files_index(root) if files_index is None else files_index
    meta = _lookup_frozen_file_entry(root, repo_path, "map_display", index)
    if not force_generate and isinstance(meta, dict):
        frozen_bytes = _frozen_file_matches_sources(root, meta)
        if frozen_bytes is not None:
            return frozen_bytes

    norm = repo_path.replace("\\", "/")
    src_path = root / norm
    airport = ""
    if not src_path.is_file():
        parts = norm.split("/")
        if len(parts) >= 2 and len(parts[-2]) == 4:
            airport = parts[-2].upper()
            cand = root / "/".join(parts[:-2]) / "map_display.json"
            if cand.is_file():
                src_path = cand
        if not src_path.is_file() and isinstance(meta, dict) and meta.get("sources"):
            src_path = root / str(next(iter(meta["sources"])))
    raw_bytes = _canonical_lf(src_path.read_bytes())
    doc = json.loads(raw_bytes.decode("utf-8"))
    base_doc = airac_overrides.resolve(doc, "") if "airac_overrides" in doc else doc
    if not airport and isinstance(base_doc.get("airport"), str):
        airport = base_doc["airport"].upper()
    converted = _convert_map_display_single(base_doc, airport=airport)
    return (json.dumps(converted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def project_procedure_options_default_bytes(
    root: Path,
    repo_path: str,
    *,
    force_generate: bool = False,
    files_index: dict[str, dict[str, object]] | None = None,
) -> bytes:
    """Return default-feed legacy procedure_options.json bytes (airac_overrides stripped)."""
    index = load_frozen_files_index(root) if files_index is None else files_index
    meta = _lookup_frozen_file_entry(root, repo_path, "procedure_options", index)
    if not force_generate and isinstance(meta, dict):
        frozen_bytes = _frozen_file_matches_sources(root, meta)
        if frozen_bytes is not None:
            doc = json.loads(frozen_bytes.decode("utf-8"))
            if "airac_overrides" not in doc:
                return frozen_bytes
            resolved = airac_overrides.resolve(doc, "")
            return (json.dumps(resolved, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    norm = repo_path.replace("\\", "/")
    apt_dir = (root / norm).parent
    if not apt_dir.is_dir() and isinstance(meta, dict) and meta.get("sources"):
        apt_dir = (root / str(next(iter(meta["sources"])))).parent

    def _load_opt(name: str) -> dict | None:
        p = apt_dir / name
        if not p.is_file():
            return None
        doc = json.loads(_canonical_lf(p.read_bytes()).decode("utf-8"))
        return airac_overrides.resolve(doc, "") if "airac_overrides" in doc else doc

    use_doc = _load_opt("procedure_use.json")
    climb_doc = _load_opt("initial_climb.json")
    dep_doc = _load_opt("departure_variants.json")
    if use_doc is None and climb_doc is None and dep_doc is None:
        legacy_p = apt_dir / "procedure_options.json"
        doc = json.loads(_canonical_lf(legacy_p.read_bytes()).decode("utf-8"))
        base = airac_overrides.resolve(doc, "") if "airac_overrides" in doc else doc
        return (json.dumps(base, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    airport = apt_dir.name.upper()
    for d in (use_doc, climb_doc, dep_doc):
        if isinstance(d, dict) and d.get("airport"):
            airport = str(d["airport"]).strip().upper()
            break
    merged = _merge_proc_single_docs(use_doc, climb_doc, dep_doc, airport=airport)
    return (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


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
    """Apply legacy projections to default & full manifests for datasets."""
    if kind == "sector_data":
        fallbacks = release_gates.load_capability_fallbacks(root)
        generated = dict(projected_bytes or {})
        archive_sources: dict[str, str] = {}
        new_full_entries: list[dict[str, object]] = []

        def _variant_entry(fentry: dict[str, object]) -> dict[str, object]:
            rp = str(fentry.get("repo_path", ""))
            orig = rp[len("airac_variants/") :] if rp.startswith("airac_variants/") else rp
            variant_repo = f"airac_variants/{orig}"
            disk_bytes = _canonical_lf((root / orig).read_bytes())
            d_sha, d_size = _file_meta(disk_bytes)
            clean = dict(fentry)
            clean["repo_path"] = variant_repo
            clean["sha256"] = d_sha
            clean["size_bytes"] = d_size
            generated[variant_repo] = disk_bytes
            archive_sources[variant_repo] = variant_repo
            return clean

        raw_entries = gated.get("full_entries", [])
        if isinstance(raw_entries, list):
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    continue
                files = entry.get("files", {})
                if not isinstance(files, dict):
                    new_full_entries.append(entry)
                    continue
                has_legacy_tma = "configs" in files or "influence" in files
                has_schema3_tma = "tma_definitions" in files and "tma_layout" in files
                has_schema3_acc = any(
                    k in files for k in ("acc_definitions", "acc_layout", "acc_coordination")
                )
                is_defaults_entry = any(
                    isinstance(fe, dict)
                    and str(fe.get("repo_path", "")).startswith(".voiceatc/defaults/")
                    for fe in files.values()
                )
                bundle_path = str(entry.get("id", ""))
                if has_legacy_tma and has_schema3_tma:
                    # Emit the legacy bundle entry first (for full-feed builds without community.airspace_files),
                    # followed by the schema-3 entry gated on community.airspace_files so capable builds overwrite it.
                    legacy_files: dict[str, object] = {}
                    for fkind in ("configs", "definitions", "influence", "tma"):
                        fentry = files.get(fkind)
                        if isinstance(fentry, dict):
                            legacy_files[fkind] = dict(fentry)
                            if fentry.get("repo_path"):
                                rp = str(fentry["repo_path"])
                                orig = rp[len("airac_variants/") :] if rp.startswith("airac_variants/") else rp
                                archive_sources[rp] = rp if rp in generated else orig
                    legacy_entry = {k: v for k, v in entry.items() if k != "files"}
                    legacy_entry["files"] = legacy_files
                    new_full_entries.append(legacy_entry)

                    if not is_defaults_entry:
                        schema3_files: dict[str, object] = {}
                        for fkind in ("tma_definitions", "tma_layout", "tma_coordination"):
                            fentry = files.get(fkind)
                            if isinstance(fentry, dict) and fentry.get("repo_path"):
                                schema3_files[fkind] = _variant_entry(fentry)
                        def_s3 = files.get("definitions_schema3")
                        if isinstance(def_s3, dict) and def_s3.get("repo_path"):
                            schema3_files["definitions"] = _variant_entry(def_s3)
                        s3_entry = {k: v for k, v in entry.items() if k != "files"}
                        base_reqs = list(entry.get("requires", [])) if isinstance(entry.get("requires"), list) else []
                        s3_entry["requires"] = sorted(set(base_reqs) | {AIRSPACE_FILES_CAPABILITY})
                        s3_entry["files"] = schema3_files
                        new_full_entries.extend(
                            _schema3_bundle_entries(
                                root,
                                bundle_path,
                                s3_entry,
                                schema3_files,
                                files,
                                generated,
                                archive_sources,
                                fallbacks,
                            )
                        )
                elif has_schema3_tma or has_schema3_acc:
                    if not is_defaults_entry:
                        schema3_files = {}
                        for fkind, fentry in files.items():
                            if isinstance(fentry, dict) and fentry.get("repo_path"):
                                schema3_files[fkind] = _variant_entry(fentry)
                            else:
                                schema3_files[fkind] = fentry
                        s3_entry = {k: v for k, v in entry.items() if k != "files"}
                        base_reqs = list(entry.get("requires", [])) if isinstance(entry.get("requires"), list) else []
                        s3_entry["requires"] = sorted(set(base_reqs) | {AIRSPACE_FILES_CAPABILITY})
                        s3_entry["files"] = schema3_files
                        new_full_entries.extend(
                            _schema3_bundle_entries(
                                root,
                                bundle_path,
                                s3_entry,
                                schema3_files,
                                files,
                                generated,
                                archive_sources,
                                fallbacks,
                            )
                        )
                else:
                    for file_entry in files.values():
                        if isinstance(file_entry, dict) and file_entry.get("repo_path"):
                            rp = str(file_entry["repo_path"])
                            orig = rp[len("airac_variants/") :] if rp.startswith("airac_variants/") else rp
                            archive_sources[rp] = rp if rp in generated else orig
                    new_full_entries.append(entry)
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
            if not rp:
                continue
            leg_bytes = generated.get(rp)
            if leg_bytes is None:
                leg_bytes = project_legacy_file_bytes(
                    root, rp, kind, force_generate=force_generate, files_index=files_index
                )
                if (root / rp).is_file():
                    disk_bytes = _canonical_lf((root / rp).read_bytes())
                    if json.loads(leg_bytes.decode("utf-8")) == json.loads(disk_bytes.decode("utf-8")):
                        leg_bytes = disk_bytes
                if not (root / rp).is_file() or leg_bytes != _canonical_lf((root / rp).read_bytes()):
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
            reqs = list(entry.get("requires", [])) if isinstance(entry.get("requires"), list) else []
            s3_rp = orig
            if not (root / orig).is_file():
                meta = _lookup_frozen_file_entry(root, orig, kind, files_index)
                if isinstance(meta, dict) and meta.get("sources"):
                    s3_rp = str(next(iter(meta["sources"])))
            if not s3_rp or not (root / s3_rp).is_file():
                new_full_entries.append(entry)
                if rp:
                    archive_sources[rp] = s3_rp or rp
                continue
            disk_bytes = _canonical_lf((root / s3_rp).read_bytes())
            leg_bytes = generated.get(orig)
            if leg_bytes is None:
                leg_bytes = project_legacy_file_bytes(
                    root, orig, kind, force_generate=force_generate, files_index=files_index
                )
            if AIRSPACE_FILES_CAPABILITY in reqs:
                new_full_entries.append(entry)
                archive_sources[rp] = s3_rp
                continue
            if rp.startswith(".voiceatc/defaults/"):
                generated[rp] = leg_bytes
                sha, size = _file_meta(leg_bytes)
                legacy_entry = dict(entry)
                legacy_entry["sha256"] = sha
                legacy_entry["size_bytes"] = size
                new_full_entries.append(legacy_entry)
                archive_sources[rp] = rp
                continue
            if rp.startswith("airac_variants/"):
                d_sha, d_size = _file_meta(disk_bytes)
                s3_entry = dict(entry)
                s3_entry["sha256"] = d_sha
                s3_entry["size_bytes"] = d_size
                s3_entry["requires"] = sorted(set(reqs) | {AIRSPACE_FILES_CAPABILITY})
                new_full_entries.append(s3_entry)
                generated[rp] = disk_bytes
                archive_sources[rp] = rp
                continue
            disk_doc = json.loads(disk_bytes.decode("utf-8"))
            leg_doc = json.loads(leg_bytes.decode("utf-8"))
            if leg_doc != disk_doc or (leg_bytes != disk_bytes and isinstance(disk_doc, dict) and disk_doc.get("schema") == 3):
                generated[orig] = leg_bytes
                sha, size = _file_meta(leg_bytes)
                legacy_entry = dict(entry)
                legacy_entry["sha256"] = sha
                legacy_entry["size_bytes"] = size
                new_full_entries.append(legacy_entry)
                archive_sources[rp] = orig

                variant_repo = f"airac_variants/{s3_rp}"
                d_sha, d_size = _file_meta(disk_bytes)
                s3_entry = dict(entry)
                s3_entry["repo_path"] = variant_repo
                s3_entry["sha256"] = d_sha
                s3_entry["size_bytes"] = d_size
                s3_entry["requires"] = sorted(set(reqs) | {AIRSPACE_FILES_CAPABILITY})
                new_full_entries.append(s3_entry)
                generated[variant_repo] = disk_bytes
                archive_sources[variant_repo] = variant_repo
            else:
                new_full_entries.append(entry)
                archive_sources[rp] = s3_rp
    gated["full_entries"] = new_full_entries
    return generated, archive_sources


def build_sector_release_projection(
    root: Path,
    source_bundles: dict[str, dict[str, object]],
    *,
    force_generate: bool = False,
) -> dict[str, object]:
    """Augment schema-3 source bundles with frozen or projected legacy and schema-1 tma files.

    Old/moved bundles (e.g. ``PALMA_TMA``, ``VALENCIA_TMA``) keep their frozen legacy bundle paths
    on the default legacy feed while canonical schema-3 files remain at their schema-3 paths.
    """
    index_bundles = load_frozen_index(root)
    fallbacks = release_gates.load_capability_fallbacks(root)
    all_acc_units: dict[str, dict] = {}
    all_acc_positions: dict[str, dict] = {}
    for acc_bundle_path, bundle_entry in source_bundles.items():
        files = bundle_entry.get("files", {}) if isinstance(bundle_entry, dict) else {}
        acc_entry = (files.get("acc_definitions") or files.get("acc_structure")) if isinstance(files, dict) else None
        if isinstance(acc_entry, dict):
            acc_path = root / str(acc_entry["repo_path"])
            resolved_acc = _fallback_file_path(root, acc_bundle_path, acc_path.name, fallbacks) or acc_path
            payload = json.loads(resolved_acc.read_text(encoding="utf-8"))
            for unit in payload.get("units", []):
                if isinstance(unit, dict) and unit.get("id"):
                    all_acc_units[str(unit["id"]).strip()] = unit
            for pos in payload.get("positions", []):
                if isinstance(pos, dict) and pos.get("call_sign"):
                    all_acc_positions[str(pos["call_sign"]).strip()] = pos

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

        if "tma_definitions" in out_files and "tma_layout" in out_files:
            index_entry = index_bundles.get(bundle_path)
            leg_bundle_path = legacy_path_for_bundle(bundle_path, index_entry)
            frozen_files = (
                None
                if force_generate
                else _frozen_bundle_files(root, bundle_path, index_entry)
            )
            cfg_repo = f"{leg_bundle_path}/sector_configs.json"
            inf_repo = f"{leg_bundle_path}/sector_influence.json"
            tma_repo = f"{leg_bundle_path}/tma.json"
            def_repo = f"{leg_bundle_path}/sector_definitions.json"
            s3_def_repo = (
                str(out_files["definitions"]["repo_path"])
                if isinstance(out_files.get("definitions"), dict)
                else f"{bundle_path}/sector_definitions.json"
            )

            # Build legacy projection dictionary keyed by leg_bundle_path for old builds
            leg_files: dict[str, object] = {}
            if frozen_files is not None:
                bundle_paths[leg_bundle_path] = "frozen"
                frozen_bundles.append(leg_bundle_path)
                cfg_bytes = frozen_files["sector_configs.json"]
                inf_bytes = frozen_files["sector_influence.json"]
                def_bytes = frozen_files["sector_definitions.json"]
                projected_bytes[cfg_repo] = cfg_bytes
                projected_bytes[inf_repo] = inf_bytes
                projected_bytes[def_repo] = def_bytes
                leg_files["configs"] = _file_entry(cfg_repo, cfg_bytes)
                leg_files["influence"] = _file_entry(inf_repo, inf_bytes)
                leg_files["definitions"] = _file_entry(def_repo, def_bytes)
                if "tma.json" in frozen_files:
                    tma_bytes = frozen_files["tma.json"]
                    projected_bytes[tma_repo] = tma_bytes
                    leg_files["tma"] = _file_entry(tma_repo, tma_bytes, requires=[TMA_FILE_CAPABILITY])
            else:
                bundle_paths[leg_bundle_path] = "generated"
                generated_bundles.append(leg_bundle_path)
                tma_defs_rel = str(out_files["tma_definitions"]["repo_path"])
                tma_layout_rel = str(out_files["tma_layout"]["repo_path"])
                tma_defs_path = _fallback_file_path(root, bundle_path, Path(tma_defs_rel).name, fallbacks) or (root / tma_defs_rel)
                tma_layout_path = _fallback_file_path(root, bundle_path, Path(tma_layout_rel).name, fallbacks) or (root / tma_layout_rel)
                tma_defs = json.loads(tma_defs_path.read_text(encoding="utf-8"))
                tma_layout = json.loads(tma_layout_path.read_text(encoding="utf-8"))
                meta = index_entry or {}
                cfg_payload, inf_payload = project_configs_and_influence(
                    tma_defs,
                    tma_layout,
                    sector_aliases=meta.get("sector_aliases"),  # type: ignore[arg-type]
                    configs_airport=meta.get("configs_airport"),  # type: ignore[arg-type]
                    influence_airport=meta.get("influence_airport"),  # type: ignore[arg-type]
                    auto_airport_for_non_prefixed=index_entry is None,
                )
                cfg_bytes = (json.dumps(cfg_payload, indent=2) + "\n").encode("utf-8")
                inf_bytes = (json.dumps(inf_payload, indent=2) + "\n").encode("utf-8")
                projected_bytes[cfg_repo] = cfg_bytes
                projected_bytes[inf_repo] = inf_bytes
                leg_files["configs"] = _file_entry(cfg_repo, cfg_bytes)
                leg_files["influence"] = _file_entry(inf_repo, inf_bytes)

                if isinstance(out_files.get("definitions"), dict):
                    def_path = _fallback_file_path(root, bundle_path, Path(s3_def_repo).name, fallbacks) or (root / s3_def_repo)
                    def_raw = _canonical_lf(def_path.read_bytes())
                    defs_doc = json.loads(def_raw.decode("utf-8"))
                    all_pos_ids = _tma_position_ids(tma_defs, tma_layout)
                    default_defs = _resolve_default_doc(defs_doc)
                    converted_defs = _convert_definitions_doc(
                        default_defs, all_pos_ids, meta.get("sector_aliases") or {}  # type: ignore[arg-type]
                    )
                    def_bytes = (
                        json.dumps(converted_defs, indent=2, ensure_ascii=False) + "\n"
                    ).encode("utf-8")
                    projected_bytes[def_repo] = def_bytes
                    leg_files["definitions"] = _file_entry(def_repo, def_bytes)

                if "tma_coordination" in out_files and (
                    index_entry is None or "tma.json" in (index_entry.get("frozen_files") or [])
                ):
                    coord_rel = str(out_files["tma_coordination"]["repo_path"])
                    coord_path = _fallback_file_path(root, bundle_path, Path(coord_rel).name, fallbacks) or (root / coord_rel)
                    tma_coordination = json.loads(coord_path.read_text(encoding="utf-8"))
                    context = bundle_airspace_context(root, bundle_path, out_files, fallbacks=fallbacks)
                    if schema3_features.used_capabilities(
                        schema3_features.agreement_rows(tma_coordination), context
                    ):
                        # An old build reads the downgraded rows, so tma.json carries them too.
                        tma_coordination = schema3_features.downgrade_document(tma_coordination, context)
                    acc_units, acc_pos = _collect_acc_data_for_bundle(
                        root, bundle_path, all_acc_units, all_acc_positions, fallbacks=fallbacks
                    )
                    bundle_key = Path(leg_bundle_path).name
                    tma_payload = project_schema1_tma(
                        tma_defs,
                        tma_layout,
                        tma_coordination,
                        acc_units,
                        bundle_key,
                        acc_positions_by_cs=acc_pos,
                        unit_aliases=meta.get("unit_aliases"),  # type: ignore[arg-type]
                        tma_name=meta.get("tma_name"),  # type: ignore[arg-type]
                    )
                    tma_bytes = (json.dumps(tma_payload, indent=2) + "\n").encode("utf-8")
                    projected_bytes[tma_repo] = tma_bytes
                    leg_files["tma"] = _file_entry(tma_repo, tma_bytes, requires=[TMA_FILE_CAPABILITY])

            if leg_bundle_path == bundle_path:
                merged = dict(leg_files)
                for kind, entry in out_files.items():
                    if kind not in ("definitions", "configs", "influence", "tma"):
                        merged[kind] = entry
                    elif kind == "definitions":
                        merged["definitions_schema3"] = entry
                projected_bundles[bundle_path] = {"files": merged}
            else:
                # Emit legacy entry at moved old path AND schema-3 entry at new canonical path
                projected_bundles[leg_bundle_path] = {"files": leg_files}
                projected_bundles[bundle_path] = {"files": out_files}
        else:
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
    parser.add_argument("--force-generate", action="store_true", help="Ignore frozen snapshots and generate all bundles from schema 3")
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
