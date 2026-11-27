"""Reference checker for tma_definitions.json / tma_layout.json / tma_coordination.json, schema 3.

Rules and message templates come from tma_rules.json. check(defs_payload, layout_payload,
bundle_key, sector_ids, acc_units=None, acc_positions=None, coordination_payload=None,
sector_catalog=None) returns every problem as a Problem(code, where, value, expected,
allowed, file_name), in the order the walk below meets them. Both game and community
checkers must produce the same (code, where) list for every case in tma_cases/cases.json.

check_bundle(bundle_dir) is the community-only entry point: it reads the bundle's own
tma_definitions/layout/coordination files, sector definitions, ancestor acc_definitions.json,
and runway presets.
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

import json
import re
from dataclasses import dataclass
from pathlib import Path

RULES_PATH = Path(__file__).with_name("tma_rules.json")
RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))
SERVICES: dict[str, dict] = RULES["services"]
SERVICE_LIST = ", ".join(SERVICES)
PLAYABLE = [name for name, row in SERVICES.items() if row["playable"]]

ICAO_RE = re.compile(r"^[A-Z0-9]{4}$")
SECTOR_RE = re.compile(r"^[A-Z0-9_]+$")
ZONE_KINDS: list[str] = list(RULES.get("zone_kinds", []))
POSITION_ROLES: list[str] = list(RULES.get("position_roles", []))
FREQ_RE = re.compile(r"^\d{3}\.\d{3}$")
LEVEL_RE = re.compile(r"^(?:[FA]\d{3}|EVEN|ODD)$")
CODE_RE = re.compile(RULES["code_pattern"])

KEYS = {
    "definitions_root": {"schema", "units", "positions", "zones"},
    "layout_root": {"schema", "configurations", "runway_combinations"},
    "coordination_root": {"schema", "agreements"},
    "unit": {"id", "call_sign", "part_of", "title", "services", "airport", "unassigned_frequencies"},
    "position": {"call_sign", "unit", "frequency", "roles", "airports"},
    "zone": {"sector", "kind", "airport"},
    "configuration_entry": {"positions", "airports", "valid_for_runways"},
    "runway_combination": {"id", "title", "airports"},
    "agreement": {"name", "from", "to", "arrives", "departs", "fix", "level", "runways"},
}


@dataclass(frozen=True)
class Problem:
    code: str
    where: str
    value: str = ""
    expected: str = ""
    allowed: str = ""
    file_name: str = ""

    def message(self, bundle_key: str) -> str:
        fname = self.file_name or str(RULES["file_name"])
        where = f"{bundle_key}/{fname} {self.where}".strip()
        return (
            RULES["messages"][self.code]
            .replace("{where}", where)
            .replace("{value}", self.value)
            .replace("{expected}", self.expected)
            .replace("{allowed}", self.allowed)
            .replace("{schema}", str(RULES["schema"]))
        )


def _is_whole(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer()


def _join(where: str, key: str) -> str:
    return f"{where}.{key}" if where else key


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if _is_whole(value):
        return str(int(value))
    if value is None:
        return "null"
    return json.dumps(value)


def _normalize_runway_ident(raw_ident: str) -> str:
    ident = str(raw_ident).strip().upper()
    if ident.startswith("RWY"):
        ident = ident[3:]
    elif ident.startswith("RW"):
        ident = ident[2:]
    return ident.strip()


class _Walk:
    def __init__(self, bundle_key: str, sector_ids: set[str], file_name: str = "") -> None:
        self.bundle_key = bundle_key
        self.sector_ids = sector_ids
        self.file_name = file_name or str(RULES["file_name"])
        self.problems: list[Problem] = []

    def add(self, code: str, where: str, value: object = "", expected: str = "", allowed: str = "") -> None:
        self.problems.append(Problem(code, where, _text(value), expected, allowed, self.file_name))

    def keys(self, node: object, kind: str, where: str) -> bool:
        if not isinstance(node, dict):
            self.add("TMA_FIELD_SHAPE", where, "an object")
            return False
        for key in sorted(set(node) - KEYS[kind]):
            self.add("TMA_UNKNOWN_KEY", where, key, allowed=", ".join(sorted(KEYS[kind])))
        return True

    def text(self, node: dict, key: str, where: str) -> str:
        if key not in node:
            self.add("TMA_FIELD_MISSING", where, key)
            return ""
        value = node[key]
        if not isinstance(value, str) or not value.strip():
            self.add("TMA_FIELD_SHAPE", _join(where, key), "a non-empty string")
            return ""
        return value

    def array(self, node: dict, key: str, where: str, required: bool = True) -> list:
        if key not in node:
            if required:
                self.add("TMA_FIELD_MISSING", where, key)
            return []
        value = node[key]
        if not isinstance(value, list) or (required and not value):
            self.add("TMA_FIELD_SHAPE", _join(where, key), "a non-empty array")
            return []
        return value

    def frequency(self, value: object, where: str) -> str:
        if isinstance(value, str) and FREQ_RE.match(value) and 118.0 <= float(value) <= 136.99:
            return value
        self.add("TMA_FREQUENCY_INVALID", where, value)
        return ""

    def level(self, value: object, where: str) -> None:
        if not isinstance(value, str) or not LEVEL_RE.match(value):
            self.add("TMA_LEVEL_INVALID", where, value)


def _check_schema(w: _Walk, payload: dict, expected_schema: int) -> bool:
    if "schema" not in payload:
        w.add("TMA_SCHEMA_MISSING", "schema")
        return False
    schema = payload["schema"]
    if not _is_whole(schema) or float(schema) < 1.0:
        w.add("TMA_FIELD_SHAPE", "schema", "a whole number")
        return False
    if int(schema) > expected_schema:
        w.add("TMA_SCHEMA_NEWER", "schema", schema)
        return False
    if int(schema) < expected_schema:
        w.add("TMA_SCHEMA_OLDER", "schema", schema)
        return False
    return True


def check(
    defs_payload: object,
    layout_payload: object,
    bundle_key: str,
    sector_ids: set[str],
    acc_units: list[dict] | None = None,
    acc_positions: list[dict] | None = None,
    coordination_payload: object = None,
    sector_catalog: dict[str, dict] | None = None,
) -> list[Problem]:
    expected_schema = int(RULES.get("schema", 3))
    w = _Walk(bundle_key, sector_ids, str(RULES.get("file_name", "tma_definitions.json")))
    if not isinstance(defs_payload, dict):
        w.add("TMA_JSON_INVALID", "")
        return w.problems
    if not _check_schema(w, defs_payload, expected_schema):
        return w.problems
    w.keys(defs_payload, "definitions_root", "")

    lw = _Walk(bundle_key, sector_ids, str(RULES.get("layout_file_name", "tma_layout.json")))
    layout: dict = {}
    if not isinstance(layout_payload, dict):
        lw.add("TMA_JSON_INVALID", "")
    else:
        layout = layout_payload
        if _check_schema(lw, layout, expected_schema):
            lw.keys(layout, "layout_root", "")

    airports = _derive_airports(layout)
    units = _check_units(w, defs_payload, airports, forbid_center=True, parent_units=acc_units or [])
    positions = _check_positions(w, defs_payload, units)
    _merge_acc_units(units, acc_units or [])
    for acc_pos in acc_positions or []:
        if isinstance(acc_pos, dict):
            pcs = str(acc_pos.get("call_sign", "")).strip()
            if pcs:
                positions[pcs] = acc_pos
    _check_zones(w, defs_payload, airports)
    catalog = sector_catalog or {}
    if layout and not lw.problems:
        _check_layout(lw, layout, units, positions, catalog)
        _check_runway_combinations(lw, layout, airports)
    w.problems.extend(lw.problems)
    if coordination_payload is not None:
        w.problems.extend(check_coordination(coordination_payload, bundle_key, units, "", positions))
    return w.problems


def check_acc(
    defs_payload: object,
    layout_payload: object,
    bundle_key: str,
    sector_ids: set[str] | None = None,
    sector_catalog: dict[str, dict] | None = None,
) -> list[Problem]:
    expected_schema = int(RULES.get("schema", 3))
    ids = sector_ids or set()
    w = _Walk(bundle_key, ids, str(RULES.get("acc_file_name", "acc_definitions.json")))
    if not isinstance(defs_payload, dict):
        w.add("TMA_JSON_INVALID", "")
        return w.problems
    if not _check_schema(w, defs_payload, expected_schema):
        return w.problems
    w.keys(defs_payload, "definitions_root", "")
    units = _check_units(w, defs_payload, [], forbid_center=False)
    positions = _check_positions(w, defs_payload, units)
    if isinstance(layout_payload, dict) and layout_payload:
        lw = _Walk(bundle_key, ids, str(RULES.get("acc_layout_file_name", "acc_layout.json")))
        if _check_schema(lw, layout_payload, expected_schema):
            lw.keys(layout_payload, "layout_root", "")
            _check_layout(lw, layout_payload, units, positions, sector_catalog or {})
        w.problems.extend(lw.problems)
    return w.problems


def check_coordination(
    payload: object,
    bundle_key: str,
    units: dict[str, dict],
    file_name: str = "",
    positions: dict[str, dict] | None = None,
) -> list[Problem]:
    coord_file = file_name or str(RULES.get("coordination_file_name", "tma_coordination.json"))
    w = _Walk(bundle_key, set(), coord_file)
    if not isinstance(payload, dict):
        w.add("TMA_JSON_INVALID", "")
        return w.problems
    if not _check_schema(w, payload, int(RULES.get("schema", 3))):
        return w.problems
    w.keys(payload, "coordination_root", "")
    _check_agreements(w, payload, units, positions or {})
    return w.problems


def _derive_airports(layout: dict) -> list[str]:
    result: list[str] = []
    configs = layout.get("configurations", {})
    if isinstance(configs, dict):
        for unit_cfgs in configs.values():
            if not isinstance(unit_cfgs, dict):
                continue
            for cfg_val in unit_cfgs.values():
                if not isinstance(cfg_val, dict):
                    continue
                apts = cfg_val.get("airports", [])
                if isinstance(apts, list):
                    for code_var in apts:
                        code = str(code_var).strip().upper()
                        if ICAO_RE.match(code) and code not in result:
                            result.append(code)
    return result


def _merge_acc_units(units: dict[str, dict], acc_units: list[dict]) -> None:
    for unit in acc_units:
        if not isinstance(unit, dict):
            continue
        uid = str(unit.get("id", "")).strip()
        if not uid or uid in units:
            continue
        raw_services = unit.get("services", [])
        if isinstance(raw_services, list) and raw_services:
            services = [str(svc) for svc in raw_services]
        elif "part_of" in unit:
            services = ["center"]
        else:
            services = []
        units[uid] = {"services": services}


def _check_units(
    w: _Walk,
    payload: dict,
    airports: list[str],
    *,
    forbid_center: bool = True,
    parent_units: list[dict] | None = None,
) -> dict[str, dict]:
    units: dict[str, dict] = {}
    for index, unit in enumerate(w.array(payload, "units", "")):
        where = f"units[{index}]"
        if not w.keys(unit, "unit", where):
            continue
        unit_id = w.text(unit, "id", where)
        if unit_id:
            where = f'units[{index}] "{unit_id}"'
            if unit_id in units:
                w.add("TMA_ID_DUPLICATE", where, unit_id)
        has_part_of = "part_of" in unit and bool(str(unit.get("part_of", "")).strip())
        raw_svcs = unit.get("services", [])
        is_sub_centre = has_part_of and (
            "services" not in unit
            or not isinstance(raw_svcs, list)
            or not raw_svcs
            or "center" in raw_svcs
        )
        if is_sub_centre:
            if "call_sign" in unit:
                w.add("TMA_UNIT_PART_OF_CALLSIGN", where, unit_id)
        else:
            w.text(unit, "call_sign", where)
        services = _check_services(w, unit, where, required=not has_part_of)
        if has_part_of and not services:
            services = ["center"]
        if forbid_center and "center" in services:
            w.add("TMA_CENTER_IN_TMA", where, unit_id)
        needing = [name for name in services if bool(SERVICES.get(name, {}).get("needs_airport", False))]
        if needing and "airport" not in unit:
            w.add("TMA_UNIT_AIRPORT_MISSING", where, needing[0])
        if "airport" in unit:
            apt = unit["airport"]
            if not isinstance(apt, str) or not ICAO_RE.match(apt):
                w.add("TMA_AIRPORT_INVALID", f"{where}.airport", apt)
            elif airports and apt not in airports:
                w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.airport", apt)
        unassigned_freqs: list[str] = []
        if "unassigned_frequencies" in unit:
            ufreqs = w.array(unit, "unassigned_frequencies", where, required=False)
            for fi, freq_val in enumerate(ufreqs):
                uf = w.frequency(freq_val, f"{where}.unassigned_frequencies[{fi}]")
                if uf:
                    unassigned_freqs.append(uf)
        if unit_id and unit_id not in units:
            units[unit_id] = {
                "services": services,
                "part_of": str(unit.get("part_of", "")),
                "unassigned_freqs": unassigned_freqs,
            }
    known_parents: set[str] = set(units)
    for parent in parent_units or []:
        if isinstance(parent, dict):
            pid = str(parent.get("id", "")).strip()
            if pid:
                known_parents.add(pid)
    for uid, uinfo in units.items():
        p_id = str(uinfo.get("part_of", ""))
        if p_id and p_id not in known_parents:
            w.add("TMA_UNIT_PART_OF_UNKNOWN", uid, p_id)
    return units


def _check_positions(w: _Walk, payload: dict, units: dict[str, dict]) -> dict[str, dict]:
    positions: dict[str, dict] = {}
    rows = w.array(payload, "positions", "", required=False)
    for index, pos in enumerate(rows):
        where = f"positions[{index}]"
        if not w.keys(pos, "position", where):
            continue
        cs = w.text(pos, "call_sign", where)
        if cs:
            where = f'positions[{index}] "{cs}"'
            if not CODE_RE.match(cs):
                w.add("TMA_UNIT_CODE", f"{where}.call_sign", cs)
            if cs in positions:
                w.add("TMA_ID_DUPLICATE", where, cs)
        unit_id = w.text(pos, "unit", where)
        if unit_id and unit_id not in units:
            w.add("TMA_UNIT_UNKNOWN", f"{where}.unit", unit_id)
        freq = w.frequency(pos.get("frequency"), f"{where}.frequency")
        if freq and unit_id in units:
            check_uid = unit_id
            seen_u: set[str] = set()
            while check_uid and check_uid not in seen_u and check_uid in units:
                seen_u.add(check_uid)
                if freq in units[check_uid].get("unassigned_freqs", []):
                    w.add("TMA_UNASSIGNED_FREQ_USED", check_uid, freq)
                check_uid = str(units[check_uid].get("part_of", ""))
        if "roles" in pos:
            seen_roles: set[str] = set()
            for r_index, role in enumerate(w.array(pos, "roles", where)):
                role_where = f"{where}.roles[{r_index}]"
                if not isinstance(role, str) or role not in POSITION_ROLES:
                    w.add("TMA_POSITION_ROLE", role_where, role, allowed=", ".join(POSITION_ROLES))
                elif role in seen_roles:
                    w.add("TMA_ID_DUPLICATE", role_where, role)
                else:
                    seen_roles.add(role)
        if "airports" in pos:
            for a_index, code in enumerate(w.array(pos, "airports", where)):
                if not isinstance(code, str) or not ICAO_RE.search(code):
                    w.add("TMA_AIRPORT_INVALID", f"{where}.airports[{a_index}]", code)
        if cs:
            positions[cs] = {"call_sign": cs, "unit": unit_id, "frequency": freq}
    return positions


def _check_services(w: _Walk, unit: dict, where: str, *, required: bool = True) -> list[str]:
    if "services" not in unit:
        if required:
            w.add("TMA_UNIT_NO_SERVICES", where, allowed=SERVICE_LIST)
        return []
    raw = unit.get("services")
    if not isinstance(raw, list) or not raw:
        w.add("TMA_UNIT_NO_SERVICES", where, allowed=SERVICE_LIST)
        return []
    known: list[str] = []
    for index, name in enumerate(raw):
        if isinstance(name, str) and name in SERVICES:
            known.append(name)
        else:
            w.add("TMA_UNIT_SERVICE_UNKNOWN", f"{where}.services[{index}]", name, allowed=SERVICE_LIST)
    return known


def _check_zones(w: _Walk, payload: dict, airports: list[str]) -> dict[str, bool]:
    zones: dict[str, bool] = {}
    for index, zone in enumerate(w.array(payload, "zones", "", required=False)):
        where = f"zones[{index}]"
        if not w.keys(zone, "zone", where):
            continue
        sector = w.text(zone, "sector", where)
        defined = False
        if sector:
            where = f'zones[{index}] "{sector}"'
            if sector in zones:
                w.add("TMA_ID_DUPLICATE", where, sector)
            elif sector not in w.sector_ids:
                w.add("TMA_SECTOR_UNDEFINED", f"{where}.sector", sector)
            else:
                defined = True
        kind = w.text(zone, "kind", where)
        if kind and kind not in ZONE_KINDS:
            w.add("TMA_ZONE_KIND", f"{where}.kind", kind, allowed=", ".join(ZONE_KINDS))
        airport = w.text(zone, "airport", where)
        if airport and airports and airport not in airports:
            w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.airport", airport)
        if defined:
            zones[sector] = True
    return zones


def _check_layout(
    w: _Walk,
    layout: dict,
    units: dict[str, dict],
    positions: dict[str, dict],
    sector_catalog: dict[str, dict],
) -> None:
    if "configurations" not in layout or not isinstance(layout["configurations"], dict):
        w.add("TMA_FIELD_MISSING", "", "configurations")
        return
    cfgs = layout["configurations"]
    for uid_var, ucfgs in cfgs.items():
        uid = str(uid_var)
        uwhere = f"configurations.{uid}"
        if uid not in units:
            w.add("TMA_UNIT_UNKNOWN", uwhere, uid)
        if not isinstance(ucfgs, dict) or not ucfgs:
            w.add("TMA_FIELD_SHAPE", uwhere, "a non-empty map of configurations")
            continue
        unit_has_seats = any(
            isinstance(c, dict) and isinstance(c.get("positions"), dict) and bool(c.get("positions"))
            for c in ucfgs.values()
        )
        for cid_var, cfg_entry in ucfgs.items():
            cid = str(cid_var)
            cwhere = f"{uwhere}.{cid}"
            if not w.keys(cfg_entry, "configuration_entry", cwhere):
                continue
            pos_map = cfg_entry.get("positions")
            if not isinstance(pos_map, dict):
                w.add("TMA_FIELD_SHAPE", f"{cwhere}.positions", "a map of position to sector ids")
                continue
            if not pos_map:
                if not unit_has_seats:
                    w.add("TMA_FIELD_SHAPE", f"{cwhere}.positions", "a non-empty map of position to sector ids")
                continue
            claimed: dict[str, bool] = {}
            for cs_var, sids in pos_map.items():
                cs = str(cs_var)
                if cs not in positions:
                    w.add("TMA_UNIT_UNKNOWN", f"{cwhere}.positions.{cs}", cs)
                if not isinstance(sids, list) or not sids:
                    w.add("TMA_FIELD_SHAPE", f"{cwhere}.positions.{cs}", "a non-empty list of sector ids")
                    continue
                for s_var in sids:
                    sid = str(s_var)
                    spot = f"{cwhere}.positions.{cs}"
                    if w.sector_ids and sid not in w.sector_ids and sid not in sector_catalog:
                        w.add("TMA_SECTOR_UNDEFINED", spot, sid)
                    else:
                        _claim_expanded(w, claimed, sid, spot, sector_catalog)


def _claim_expanded(
    w: _Walk, claimed: dict[str, bool], sid: str, where: str, catalog: dict[str, dict]
) -> None:
    entry = catalog.get(sid, {})
    made_of = entry.get("made_of") if isinstance(entry, dict) else None
    if isinstance(made_of, list) and made_of:
        for child in made_of:
            _claim_expanded(w, claimed, str(child), where, catalog)
        return
    if sid in claimed:
        w.add("TMA_SECTOR_TWICE", where, sid)
    else:
        claimed[sid] = True


def _check_runway_combinations(w: _Walk, layout: dict, airports: list[str]) -> None:
    rows = w.array(layout, "runway_combinations", "", required=False)
    seen: set[str] = set()
    for index, row in enumerate(rows):
        where = f"runway_combinations[{index}]"
        if not w.keys(row, "runway_combination", where):
            continue
        rid = w.text(row, "id", where)
        if rid:
            where = f'runway_combinations[{index}] "{rid}"'
            if rid in seen:
                w.add("TMA_ID_DUPLICATE", where, rid)
            seen.add(rid)
        w.text(row, "title", where)
        named = row.get("airports", {})
        if not isinstance(named, dict) or not named:
            w.add("TMA_FIELD_SHAPE", f"{where}.airports", "a map of ICAO to runway preset id")
            continue
        for code_var in named:
            code = str(code_var)
            if airports and code not in airports:
                w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.airports", code)


def _check_agreement_fixes(w: _Walk, row: dict, where: str) -> list[str]:
    if "fix" not in row:
        return [""]
    raw_fix = row["fix"]
    if not isinstance(raw_fix, list) or not raw_fix:
        w.add("TMA_FIELD_SHAPE", f"{where}.fix", "a non-empty array")
        return [""]
    out: list[str] = []
    for idx, item in enumerate(raw_fix):
        if not isinstance(item, str) or not item.strip():
            w.add("TMA_FIELD_SHAPE", f"{where}.fix[{idx}]", "a non-empty string")
        else:
            token = item.strip().upper()
            if token not in out:
                out.append(token)
    return out if out else [""]


def _runway_keys(raw: object) -> list[str]:
    keys: list[str] = []
    if isinstance(raw, list):
        for value in raw:
            runway = _normalize_runway_ident(str(value))
            if runway and runway not in keys:
                keys.append(runway)
    return keys or ["*"]


def _tied_row(taken: dict[str, str], runways: list[str]) -> str:
    for runway in runways:
        if runway in taken:
            return str(taken[runway])
        if runway == "*" and taken:
            return str(next(iter(taken.values())))
    return str(taken.get("*", ""))


def _agreement_codes(raw: list) -> list[str]:
    codes: list[str] = []
    for value in raw:
        token = str(value).strip().upper()
        if token and token not in codes:
            codes.append(token)
    return codes


def _pairs_match(a_orig: str, a_dest: str, b_orig: str, b_dest: str) -> bool:
    orig_ok = a_orig == "*" or b_orig == "*" or a_orig == b_orig
    dest_ok = a_dest == "*" or b_dest == "*" or a_dest == b_dest
    return orig_ok and dest_ok


def _check_agreements(
    w: _Walk,
    payload: dict,
    units: dict[str, dict],
    positions: dict[str, dict],
) -> None:
    covered: dict[str, dict[str, dict[str, str]]] = {}
    rows = w.array(payload, "agreements", "", required=False)
    for index, row in enumerate(rows):
        where = f"agreements[{index}]"
        if not w.keys(row, "agreement", where):
            continue
        name = w.text(row, "name", where)
        if name:
            where = f'agreements[{index}] "{name}"'
        ends = [w.text(row, key, where) for key in ("from", "to")]
        for key, eid in zip(("from", "to"), ends):
            if eid and eid not in units and eid not in positions:
                w.add("TMA_UNIT_UNKNOWN", f"{where}.{key}", eid)
        if ends[0] and ends[0] == ends[1]:
            w.add("TMA_AGREEMENT_SAME_UNIT", where, name)
        fixes = _check_agreement_fixes(w, row, where)
        departs = _agreement_codes(w.array(row, "departs", where, required=False))
        arrives = _agreement_codes(w.array(row, "arrives", where, required=False))
        if "level" not in row:
            w.add("TMA_AGREEMENT_NO_LEVEL", where, name)
        else:
            w.level(row["level"], f"{where}.level")
        rwys = w.array(row, "runways", where, required=False)
        rwy_keys = _runway_keys(rwys)
        pos_ends = sum(1 for eid in ends if eid in positions and eid not in units)
        rank = pos_ends * 4 + (2 if rwys else 0) + (1 if "fix" in row else 0)
        origs = departs or ["*"]
        dests = arrives or ["*"]
        flow_kind = (
            "PARITY"
            if (not departs and not arrives)
            else (
                "DEP"
                if (departs and not arrives)
                else ("ARR" if (arrives and not departs) else "BOTH")
            )
        )
        tied_reported: dict[str, bool] = {}
        for fix_token in fixes:
            slot = f"{ends[0]}|{ends[1]}|{flow_kind}|{fix_token}|{rank}"
            bucket = covered.setdefault(slot, {})
            for orig in origs:
                for dest in dests:
                    for existing_key, existing_taken in bucket.items():
                        parts = existing_key.split("|")
                        if not _pairs_match(orig, dest, parts[0], parts[1]):
                            continue
                        other = _tied_row(existing_taken, rwy_keys)
                        if other and other not in tied_reported:
                            tied_reported[other] = True
                            w.add("TMA_AGREEMENT_TIE", where, name, expected=other)
                    pair_key = f"{orig}|{dest}"
                    taken = bucket.setdefault(pair_key, {})
                    for runway in rwy_keys:
                        taken.setdefault(runway, name)


def _acc_documents(directory: Path) -> tuple[list[dict], list[dict]]:
    acc_name = str(RULES.get("acc_file_name", "acc_definitions.json"))
    try:
        doc = json.loads((directory / acc_name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    if isinstance(doc, dict):
        raw_units = doc.get("units", [])
        raw_positions = doc.get("positions", [])
        return (
            [u for u in raw_units if isinstance(u, dict)] if isinstance(raw_units, list) else [],
            [p for p in raw_positions if isinstance(p, dict)] if isinstance(raw_positions, list) else [],
        )
    return [], []


def _ancestor_acc(bundle_dir: Path) -> tuple[list[dict], list[dict]]:
    directory = _ancestor_acc_dir(bundle_dir)
    return _acc_documents(directory) if directory is not None else ([], [])


def _ancestor_acc_dir(bundle_dir: Path) -> Path | None:
    """The nearest ancestor of the bundle that holds acc_definitions.json, or None."""
    acc_name = str(RULES.get("acc_file_name", "acc_definitions.json"))
    cur = bundle_dir.resolve().parent
    while cur != cur.parent:
        if (cur / acc_name).is_file():
            return cur
        cur = cur.parent
    return None


def _centre_ids(units: list[dict]) -> set[str]:
    """The ids a neighbour folder offers: its `center` units and their `part_of` children."""
    ids: set[str] = set()
    for unit in units:
        unit_id = str(unit.get("id", "")).strip()
        services = unit.get("services", [])
        if unit_id and isinstance(services, list) and "center" in services:
            ids.add(unit_id)
    changed = True
    while changed:
        changed = False
        for unit in units:
            child_id = str(unit.get("id", "")).strip()
            if child_id and child_id not in ids and str(unit.get("part_of", "")).strip() in ids:
                ids.add(child_id)
                changed = True
    return ids


def _neighbour_acc(directory: Path) -> tuple[list[dict], list[dict]]:
    """What a neighbour FIR folder gives a bundle's rows: its centre units with their children,
    and the positions those ids work. Its other units are not the bundle's to use."""
    units, positions = _acc_documents(directory)
    ids = _centre_ids(units)
    return (
        [unit for unit in units if str(unit.get("id", "")).strip() in ids],
        [position for position in positions
         if str(position.get("unit", "")).strip() in ids
         or str(position.get("call_sign", "")).strip() in ids],
    )


def _fir_acc(bundle_dir: Path, code: str) -> tuple[list[dict], list[dict]]:
    """The centre documents of the FIR folder `<root>/<P[0]>/<P[0:2]>/<P>`, or `<root>/<P[0]>/<P>`.

    The root is the one the bundle's own FIR folder stands in, by the same two layouts; a bundle
    outside both, or a code with no such folder, yields nothing.
    """
    acc_name = str(RULES.get("acc_file_name", "acc_definitions.json"))
    root = _fir_root(_ancestor_acc_dir(bundle_dir))
    if root is None or not ICAO_RE.fullmatch(code):
        return [], []
    for candidate in (root / code[0] / code[:2] / code, root / code[0] / code):
        if (candidate / acc_name).is_file():
            return _neighbour_acc(candidate)
    return [], []


def _fir_root(acc_dir: Path | None) -> Path | None:
    """The root `acc_dir` stands in, laid out `<root>/P/PC/FIR` or `<root>/P/FIR`, or None."""
    if acc_dir is None or len(acc_dir.name) != 4:
        return None
    parent = acc_dir.parent
    if parent.name.upper() == acc_dir.name.upper()[:2] and len(parent.parent.name) == 1:
        return parent.parent.parent
    return parent.parent if len(parent.name) == 1 else None


def _row_ends(payload: object) -> list[str]:
    """Every coordination row end ('from' and 'to'), in row order, once each."""
    ends: list[str] = []
    if not isinstance(payload, dict):
        return ends
    rows = payload.get("agreements", [])
    if not isinstance(rows, list):
        return ends
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("from", "to"):
            end = str(row.get(key, "")).strip()
            if end and end not in ends:
                ends.append(end)
    return ends


def _declared_ids(defs_payload: object, layout_payload: object) -> set[str]:
    """Every unit id and position call sign the bundle itself defines."""
    ids: set[str] = set()
    for payload in (defs_payload, layout_payload):
        if not isinstance(payload, dict):
            continue
        for unit in payload.get("units", []) if isinstance(payload.get("units"), list) else []:
            if isinstance(unit, dict) and str(unit.get("id", "")).strip():
                ids.add(str(unit["id"]).strip())
        for pos in payload.get("positions", []) if isinstance(payload.get("positions"), list) else []:
            if isinstance(pos, dict) and str(pos.get("call_sign", "")).strip():
                ids.add(str(pos["call_sign"]).strip())
        configs = payload.get("configurations")
        if isinstance(configs, dict):
            ids.update(str(unit_id) for unit_id in configs)
    return ids


def _sector_ids_and_catalog(bundle_dir: Path) -> tuple[set[str], dict[str, dict]]:
    try:
        document = json.loads((bundle_dir / "sector_definitions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), {}
    if not isinstance(document, dict):
        return set(), {}
    definitions = airac_overrides.resolve(document, "")
    out: set[str] = set()
    catalog: dict[str, dict] = {}
    sectors = definitions.get("sectors")
    if isinstance(sectors, dict):
        for sid, entry in sectors.items():
            tok = str(sid).strip().upper()
            if tok:
                out.add(tok)
                if isinstance(entry, dict):
                    catalog[tok] = entry
    rows = definitions.get("volumes", definitions.get("sector_definitions", definitions.get("definitions", [])))
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_ids = row.get("sector_ids")
            if isinstance(raw_ids, list):
                for item in raw_ids:
                    tok = str(item).strip().upper()
                    if tok:
                        out.add(tok)
            else:
                val = _row_value(row).strip().upper()
                if val:
                    out.add(val)
    elif isinstance(sectors, list):
        for row in sectors:
            if not isinstance(row, dict):
                continue
            val = _row_value(row).strip().upper()
            if val:
                out.add(val)
    return out, catalog


def _row_value(row: dict) -> str:
    for key in ("sector_id", "sector", "id", "SECTOR_ID"):
        if key in row:
            return str(row[key])
    return ""


def _unknown_runway_presets(layout: object, bundle_dir: Path) -> list[Problem]:
    """Every runway preset valid_for_runways or runway_combinations asks for that runway_configs.json lacks."""
    if not isinstance(layout, dict):
        return []
    problems: list[Problem] = []
    layout_fname = str(RULES.get("layout_file_name", "tma_layout.json"))
    configs = layout.get("configurations")
    if isinstance(configs, dict):
        for uid in sorted(str(k) for k in configs):
            ucfgs = configs.get(uid)
            if not isinstance(ucfgs, dict):
                continue
            for cid in sorted(str(k) for k in ucfgs):
                entry = ucfgs.get(cid)
                if not isinstance(entry, dict):
                    continue
                valid_rwys = entry.get("valid_for_runways")
                if not isinstance(valid_rwys, dict):
                    continue
                for code in sorted(str(k) for k in valid_rwys):
                    presets = valid_rwys.get(code)
                    if not ICAO_RE.fullmatch(code) or not isinstance(presets, list):
                        continue
                    known = _preset_ids(bundle_dir / code)
                    for preset in presets:
                        if isinstance(preset, str) and preset not in known:
                            problems.append(
                                Problem(
                                    "TMA_RUNWAY_PRESET_UNKNOWN",
                                    f"configurations.{uid}.{cid}.valid_for_runways.{code}",
                                    preset,
                                    expected=code,
                                    file_name=layout_fname,
                                )
                            )
    combos = layout.get("runway_combinations")
    if isinstance(combos, list):
        for idx, row in enumerate(combos):
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            where = f'runway_combinations[{idx}] "{rid}"' if isinstance(rid, str) and rid else f"runway_combinations[{idx}]"
            airports = row.get("airports")
            if not isinstance(airports, dict):
                continue
            for code in sorted(str(k) for k in airports):
                preset = airports.get(code)
                if not ICAO_RE.fullmatch(code) or not isinstance(preset, str) or not preset.strip():
                    continue
                known = _preset_ids(bundle_dir / code)
                if preset not in known:
                    problems.append(
                        Problem(
                            "TMA_RUNWAY_PRESET_UNKNOWN",
                            f"{where}.airports.{code}",
                            preset,
                            expected=code,
                            file_name=layout_fname,
                        )
                    )
    return problems


def _preset_ids(airport_dir: Path) -> set[str]:
    try:
        document = json.loads((airport_dir / "runway_configs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(document, dict):
        return set()
    rows = document.get("runway_configs", document.get("runway_configurations", []))
    if not isinstance(rows, list):
        return set()
    return {str(row["id"]) for row in rows if isinstance(row, dict) and "id" in row}


def check_bundle(bundle_dir: Path) -> list[str]:
    """Every problem sentence for `<bundle_dir>/tma_definitions.json` + `tma_layout.json`, in walk order; empty when absent."""
    defs_name = str(RULES.get("file_name", "tma_definitions.json"))
    layout_name = str(RULES.get("layout_file_name", "tma_layout.json"))
    coord_name = str(RULES.get("coordination_file_name", "tma_coordination.json"))

    defs_path = bundle_dir / defs_name
    layout_path = bundle_dir / layout_name
    if not defs_path.is_file() and not layout_path.is_file():
        return []
    bundle_key = bundle_dir.name
    try:
        defs_payload: object = json.loads(defs_path.read_text(encoding="utf-8")) if defs_path.is_file() else []
    except (OSError, ValueError):
        return [Problem("TMA_JSON_INVALID", "", file_name=defs_name).message(bundle_key)]
    try:
        layout_payload: object = json.loads(layout_path.read_text(encoding="utf-8")) if layout_path.is_file() else []
    except (OSError, ValueError):
        layout_payload = []

    coord_path = bundle_dir / coord_name
    coordination_payload: object = None
    if coord_path.is_file():
        try:
            coordination_payload = json.loads(coord_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            coordination_payload = []

    sector_ids, sector_catalog = _sector_ids_and_catalog(bundle_dir)
    acc_units, acc_positions = _ancestor_acc(bundle_dir)
    acc_dir = _ancestor_acc_dir(bundle_dir)
    if acc_dir is not None:
        _, acc_catalog = _sector_ids_and_catalog(acc_dir)
        sector_catalog.update(acc_catalog)
        sector_ids.update(acc_catalog)
    own_fir = acc_dir.name.upper() if acc_dir is not None else ""
    known = _declared_ids(defs_payload, layout_payload)
    for unit in acc_units:
        known.add(str(unit.get("id", "")).strip())
    for pos in acc_positions:
        known.add(str(pos.get("call_sign", "")).strip())
    seen: set[str] = set()
    for end in _row_ends(coordination_payload):
        if not own_fir or end in known:
            continue
        code = end.strip().upper()[:4]
        if code == own_fir or code in seen:
            continue
        seen.add(code)
        units, positions = _fir_acc(bundle_dir, code)
        acc_units = acc_units + units
        acc_positions = acc_positions + positions
    problems = check(
        defs_payload,
        layout_payload,
        bundle_key,
        sector_ids,
        acc_units,
        acc_positions,
        coordination_payload,
        sector_catalog,
    )
    problems.extend(_unknown_runway_presets(layout_payload, bundle_dir))
    return [problem.message(bundle_key) for problem in problems]
