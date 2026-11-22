"""Reference checker for tma_structure.json / tma_coordination.json, schema 2.

Rules and message templates come from tma_rules.json. check(payload, bundle_key,
sector_ids, acc_units=None, coordination_payload=None) returns every problem as a
Problem(code, where, value, expected, allowed, file_name), in the order the walk below
meets them. Both game and community checkers must produce the same (code, where) list
for every case in tma_cases/cases.json.

check_bundle(bundle_dir) is the community-only entry point: it reads the bundle's own
sector definitions, coordination file, ancestor acc_structure.json, and runway presets.
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
NAME_RE = re.compile(r"^[A-Z0-9]+( \+ [A-Z0-9]+)*$")
DUTY_NAME_RE = re.compile(r"^[A-Z0-9]+(( \+ | )[A-Z0-9]+)*$")
ZONE_KINDS: list[str] = list(RULES.get("zone_kinds", []))
FREQ_RE = re.compile(r"^\d{3}\.\d{3}$")
LEVEL_RE = re.compile(r"^[FA]\d{3}$")
CODE_RE = re.compile(RULES["code_pattern"])

KEYS = {
    "root": {"schema", "units", "zones", "layouts", "configurations"},
    "coordination_root": {"schema", "agreements"},
    "acc_root": {"schema", "units"},
    "unit": {"id", "call_sign", "services", "airport", "frequencies"},
    "zone": {"sector", "kind", "airport"},
    "layout": {"id", "airports", "runways", "positions", "on_duty"},
    "configuration": {"id", "name", "airports"},
    "position": {"sector", "name", "code", "unit", "frequency", "zones"},
    "on_duty": {"unit", "name", "code", "frequency", "sectors"},
    "agreement": {"name", "from", "to", "departs", "arrives", "fix", "climb", "descent", "priority",
                  "release_kind", "miles_in_trail", "go_around", "traffic_of_interest", "holding",
                  "runways"},
    "go_around": {"to", "climb"},
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
        return (RULES["messages"][self.code].replace("{where}", where).replace("{value}", self.value)
                .replace("{expected}", self.expected).replace("{allowed}", self.allowed)
                .replace("{schema}", str(RULES["schema"])))


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
    payload: object,
    bundle_key: str,
    sector_ids: set[str],
    acc_units: list[dict] | None = None,
    coordination_payload: object = None,
) -> list[Problem]:
    expected_schema = int(RULES.get("schema", 2))
    w = _Walk(bundle_key, sector_ids, str(RULES["file_name"]))
    if not isinstance(payload, dict):
        w.add("TMA_JSON_INVALID", "")
        return w.problems
    if not _check_schema(w, payload, expected_schema):
        return w.problems
    w.keys(payload, "root", "")
    airports = _derive_airports(payload)
    units = _units(w, payload, airports, forbid_center=True)
    _merge_acc_units(units, acc_units or [])
    zones = _zones(w, payload, airports)
    _layouts(w, payload, airports, units, zones)
    _configurations(w, payload, airports)
    if coordination_payload is not None:
        w.problems.extend(check_coordination(coordination_payload, bundle_key, units))
    return w.problems


def check_coordination(
    payload: object,
    bundle_key: str,
    units: dict[str, dict],
    file_name: str = "",
) -> list[Problem]:
    coord_file = file_name or str(RULES.get("coordination_file_name", "tma_coordination.json"))
    w = _Walk(bundle_key, set(), coord_file)
    if not isinstance(payload, dict):
        w.add("TMA_JSON_INVALID", "")
        return w.problems
    if not _check_schema(w, payload, int(RULES.get("schema", 2))):
        return w.problems
    w.keys(payload, "coordination_root", "")
    _agreements(w, payload, units)
    return w.problems


def check_acc_structure(payload: object, bundle_key: str) -> list[Problem]:
    acc_file = str(RULES.get("acc_file_name", "acc_structure.json"))
    w = _Walk(bundle_key, set(), acc_file)
    if not isinstance(payload, dict):
        w.add("TMA_JSON_INVALID", "")
        return w.problems
    if not _check_schema(w, payload, int(RULES.get("schema", 2))):
        return w.problems
    w.keys(payload, "acc_root", "")
    _units(w, payload, [], forbid_center=False)
    return w.problems


def _derive_airports(payload: dict) -> list[str]:
    result: list[str] = []
    raw_layouts = payload.get("layouts", [])
    if isinstance(raw_layouts, list):
        for layout in raw_layouts:
            if not isinstance(layout, dict):
                continue
            raw_apts = layout.get("airports", [])
            if not isinstance(raw_apts, list):
                continue
            for code in raw_apts:
                if isinstance(code, str) and ICAO_RE.match(code) and code not in result:
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
        services = [str(svc) for svc in raw_services] if isinstance(raw_services, list) else []
        raw_freqs = unit.get("frequencies", [])
        frequencies = {str(freq) for freq in raw_freqs} if isinstance(raw_freqs, list) else set()
        units[uid] = {"services": services, "frequencies": frequencies}


def _units(w: _Walk, payload: dict, airports: list[str], *, forbid_center: bool = True) -> dict[str, dict]:
    units: dict[str, dict] = {}
    for i, unit in enumerate(w.array(payload, "units", "")):
        where = f"units[{i}]"
        if not w.keys(unit, "unit", where):
            continue
        unit_id = w.text(unit, "id", where)
        if unit_id:
            where = f'units[{i}] "{unit_id}"'
            if unit_id in units:
                w.add("TMA_ID_DUPLICATE", where, unit_id)
        w.text(unit, "call_sign", where)
        services = _services(w, unit, where)
        if forbid_center and "center" in services:
            w.add("TMA_CENTER_IN_TMA", where, unit_id)
        needing = [name for name in services if SERVICES[name]["needs_airport"]]
        if needing and "airport" not in unit:
            w.add("TMA_UNIT_AIRPORT_MISSING", where, needing[0])
        if "airport" in unit:
            apt = unit["airport"]
            if not isinstance(apt, str) or not ICAO_RE.match(apt):
                w.add("TMA_AIRPORT_INVALID", f"{where}.airport", apt)
            elif airports and apt not in airports:
                w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.airport", apt)
        frequencies = [w.frequency(f, f"{where}.frequencies[{j}]")
                       for j, f in enumerate(w.array(unit, "frequencies", where))]
        if unit_id and unit_id not in units:
            units[unit_id] = {"services": services, "frequencies": {f for f in frequencies if f}}
    return units


def _services(w: _Walk, unit: dict, where: str) -> list[str]:
    raw = unit.get("services")
    if not isinstance(raw, list) or not raw:
        w.add("TMA_UNIT_NO_SERVICES", where, allowed=SERVICE_LIST)
        return []
    known: list[str] = []
    for j, name in enumerate(raw):
        if isinstance(name, str) and name in SERVICES:
            known.append(name)
        else:
            w.add("TMA_UNIT_SERVICE_UNKNOWN", f"{where}.services[{j}]", name, allowed=SERVICE_LIST)
    return known


def _zones(w: _Walk, payload: dict, airports: list[str]) -> set[str]:
    """The top-level zones: each a defined sector, CTR or ATZ, of an airport in the file."""
    zones: set[str] = set()
    for i, zone in enumerate(w.array(payload, "zones", "", required=False)):
        where = f"zones[{i}]"
        if not w.keys(zone, "zone", where):
            continue
        sector = w.text(zone, "sector", where)
        defined = False
        if sector:
            where = f'zones[{i}] "{sector}"'
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
        if airport and airport not in airports:
            w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.airport", airport)
        if defined:
            zones.add(sector)
    return zones


def _layouts(w: _Walk, payload: dict, _airports: list[str], units: dict[str, dict], zones: set[str]) -> None:
    seen: set[str] = set()
    for i, layout in enumerate(w.array(payload, "layouts", "")):
        where = f"layouts[{i}]"
        if not w.keys(layout, "layout", where):
            continue
        layout_id = w.text(layout, "id", where)
        if layout_id:
            where = f'layouts[{i}] "{layout_id}"'
            if layout_id in seen:
                w.add("TMA_ID_DUPLICATE", where, layout_id)
            seen.add(layout_id)
        layout_airports = _layout_airports(w, layout, where)
        _runways(w, layout, where, layout_airports)
        sectors: set[str] = set()
        for k, position in enumerate(w.array(layout, "positions", where)):
            _position(w, position, f"{where}.positions[{k}]", units, sectors, zones)
        _on_duty(w, layout, where, units, sectors)


def _layout_airports(w: _Walk, layout: dict, where: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for offset, code in enumerate(w.array(layout, "airports", where)):
        at = f"{where}.airports[{offset}]"
        if not isinstance(code, str) or not ICAO_RE.match(code):
            w.add("TMA_AIRPORT_INVALID", at, code)
        elif code in seen:
            w.add("TMA_ID_DUPLICATE", at, code)
        else:
            seen.add(code)
            out.append(code)
    return out


def _runways(w: _Walk, layout: dict, where: str, airports: list[str]) -> None:
    if "runways" not in layout:
        return
    runways = layout["runways"]
    if not isinstance(runways, dict) or not runways:
        w.add("TMA_FIELD_SHAPE", f"{where}.runways", "an object of airport to runway preset ids")
        return
    for code in sorted(str(k) for k in runways):
        if airports and code not in airports:
            w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.runways", code)
        presets = runways[code]
        if not isinstance(presets, list) or not presets or not all(isinstance(p, str) and p.strip() for p in presets):
            w.add("TMA_FIELD_SHAPE", f"{where}.runways.{code}", "a non-empty array of runway preset ids")


def _position(w: _Walk, position: object, where: str, units: dict[str, dict],
              sectors: set[str], zones: set[str]) -> None:
    if not w.keys(position, "position", where):
        return
    _position_sector(w, position, where, sectors)
    if "name" not in position:
        w.add("TMA_FIELD_MISSING", where, "name")
    elif not isinstance(position["name"], str) or not NAME_RE.match(position["name"]):
        w.add("TMA_POSITION_NAME", f"{where}.name", position["name"])
    _code(w, position, where)
    unit_id = w.text(position, "unit", where)
    unit = units.get(unit_id)
    if unit_id and unit is None:
        w.add("TMA_UNIT_UNKNOWN", f"{where}.unit", unit_id)
    elif unit is not None and not any(name in PLAYABLE for name in unit["services"]):
        w.add("TMA_POSITION_NOT_PLAYABLE", f"{where}.unit", unit_id, allowed=", ".join(PLAYABLE))
    if "frequency" not in position:
        w.add("TMA_FIELD_MISSING", where, "frequency")
    else:
        frequency = w.frequency(position["frequency"], f"{where}.frequency")
        if frequency and unit is not None and frequency not in unit["frequencies"]:
            w.add("TMA_POSITION_FREQUENCY_NOT_UNITS", f"{where}.frequency", frequency, expected=unit_id)
    for m, zone_id in enumerate(w.array(position, "zones", where, required=False)):
        at = f"{where}.zones[{m}]"
        if not isinstance(zone_id, str) or zone_id not in zones:
            w.add("TMA_ZONE_UNKNOWN", at, zone_id)
        else:
            _claim(w, sectors, zone_id, at)


def _on_duty(w: _Walk, layout: dict, where: str, units: dict[str, dict], sectors: set[str]) -> None:
    """The other units working the combination: known units on their own frequencies, on free sectors."""
    for k, row in enumerate(w.array(layout, "on_duty", where, required=False)):
        at = f"{where}.on_duty[{k}]"
        if not w.keys(row, "on_duty", at):
            continue
        unit_id = w.text(row, "unit", at)
        unit = units.get(unit_id)
        if unit_id and unit is None:
            w.add("TMA_UNIT_UNKNOWN", f"{at}.unit", unit_id)
        if "name" not in row:
            w.add("TMA_FIELD_MISSING", at, "name")
        elif not isinstance(row["name"], str) or not DUTY_NAME_RE.match(row["name"]):
            w.add("TMA_ON_DUTY_NAME", f"{at}.name", row["name"])
        _code(w, row, at)
        if "frequency" not in row:
            w.add("TMA_FIELD_MISSING", at, "frequency")
        else:
            frequency = w.frequency(row["frequency"], f"{at}.frequency")
            if frequency and unit is not None and frequency not in unit["frequencies"]:
                w.add("TMA_POSITION_FREQUENCY_NOT_UNITS", f"{at}.frequency", frequency, expected=unit_id)
        for m, sector in enumerate(w.array(row, "sectors", at)):
            spot = f"{at}.sectors[{m}]"
            if not isinstance(sector, str) or sector not in w.sector_ids:
                w.add("TMA_SECTOR_UNDEFINED", spot, sector)
            else:
                _claim(w, sectors, sector, spot)


def _code(w: _Walk, entry: dict, where: str) -> None:
    """A position's or on_duty unit's code: its ICAO, words joined by "_", then TWR, APP or CTR."""
    if "code" not in entry:
        w.add("TMA_FIELD_MISSING", where, "code")
    elif not isinstance(entry["code"], str) or not CODE_RE.match(entry["code"]):
        w.add("TMA_UNIT_CODE", f"{where}.code", entry["code"])


def _claim(w: _Walk, sectors: set[str], sector: str, where: str) -> None:
    """One worker per sector in a layout, positions and on_duty entries together."""
    if sector in sectors:
        w.add("TMA_SECTOR_TWICE", where, sector)
    else:
        sectors.add(sector)


def _position_sector(w: _Walk, position: dict, where: str, sectors: set[str]) -> None:
    if "sector" not in position:
        w.add("TMA_FIELD_MISSING", where, "sector")
        return
    sector = position["sector"]
    if not isinstance(sector, str) or not SECTOR_RE.match(sector):
        w.add("TMA_POSITION_ONE_SECTOR", f"{where}.sector", sector)
    elif sector not in w.sector_ids:
        w.add("TMA_SECTOR_UNDEFINED", f"{where}.sector", sector)
    else:
        _claim(w, sectors, sector, f"{where}.sector")


def _configurations(w: _Walk, payload: dict, airports: list[str]) -> None:
    """One runway preset id per airport of the file, in every configuration."""
    seen: set[str] = set()
    for i, row in enumerate(w.array(payload, "configurations", "", required=False)):
        where = f"configurations[{i}]"
        if not w.keys(row, "configuration", where):
            continue
        configuration_id = w.text(row, "id", where)
        if configuration_id:
            where = f'configurations[{i}] "{configuration_id}"'
            if configuration_id in seen:
                w.add("TMA_ID_DUPLICATE", where, configuration_id)
            seen.add(configuration_id)
        w.text(row, "name", where)
        _configuration_airports(w, row, where, airports)


def _configuration_airports(w: _Walk, row: dict, where: str, airports: list[str]) -> None:
    if "airports" not in row:
        w.add("TMA_FIELD_MISSING", where, "airports")
        return
    named = row["airports"]
    if not isinstance(named, dict) or not named:
        w.add("TMA_FIELD_SHAPE", f"{where}.airports", "an object of airport to runway preset id")
        return
    for code in sorted(str(key) for key in named):
        if code not in airports:
            w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.airports", code)
        preset = named[code]
        if not isinstance(preset, str) or not preset.strip():
            w.add("TMA_FIELD_SHAPE", f"{where}.airports.{code}", "a runway preset id")
    for code in airports:
        if code not in named:
            w.add("TMA_FIELD_MISSING", f"{where}.airports", code)


def _runway_keys(raw) -> list[str]:
    """A row's runway ends as tie keys; "*" for a row naming none, which matches every runway."""
    keys: list[str] = []
    if isinstance(raw, list):
        for value in raw:
            runway = str(value).strip().upper()
            if runway.startswith("RWY"):
                runway = runway[3:]
            elif runway.startswith("RW"):
                runway = runway[2:]
            runway = runway.strip()
            if runway and runway not in keys:
                keys.append(runway)
    return keys or ["*"]


def _tied_row(taken: dict[str, str], runways: list[str]) -> str:
    """The row already in this slot that a flow on one of `runways` would also match, else ""."""
    for runway in runways:
        if runway in taken:
            return taken[runway]
        if runway == "*" and taken:
            return next(iter(taken.values()))
    return taken.get("*", "")


def _check_agreement_fixes(w: _Walk, row: dict, where: str) -> list[str]:
    if _departure_without_fix(row):
        return [""]
    if "fix" not in row:
        w.add("TMA_FIELD_MISSING", where, "fix")
        return [""]
    raw_fix = row["fix"]
    if not isinstance(raw_fix, list) or not raw_fix:
        w.add("TMA_FIELD_SHAPE", f"{where}.fix", "a non-empty array")
        return [""]
    fixes: list[str] = []
    for index, item in enumerate(raw_fix):
        if not isinstance(item, str) or not item.strip():
            w.add("TMA_FIELD_SHAPE", f"{where}.fix[{index}]", "a non-empty string")
        else:
            token = item.strip().upper()
            if token not in fixes:
                fixes.append(token)
    return fixes if fixes else [""]


def _agreement_codes(raw: list) -> list[str]:
    codes: list[str] = []
    for value in raw:
        token = str(value).strip().upper()
        if token and token not in codes:
            codes.append(token)
    return codes


def _agreement_flows(departs: list[str], arrives: list[str], levels: list[str]) -> list[str]:
    flows: list[str] = []
    if departs and ("climb" in levels or ("descent" not in levels and not arrives)):
        flows.append("DEP")
    if arrives and ("descent" in levels or ("climb" not in levels and not departs)):
        flows.append("ARR")
    if not flows:
        if departs:
            flows.append("DEP")
        if arrives:
            flows.append("ARR")
    return flows


def _pairs_match(a_orig: str, a_dest: str, b_orig: str, b_dest: str) -> bool:
    orig_ok = a_orig == "*" or b_orig == "*" or a_orig == b_orig
    dest_ok = a_dest == "*" or b_dest == "*" or a_dest == b_dest
    return orig_ok and dest_ok


def _agreements(w: _Walk, payload: dict, units: dict[str, dict]) -> None:
    covered: dict[tuple[str, str, str, str, int], dict[tuple[str, str], dict[str, str]]] = {}
    for i, row in enumerate(w.array(payload, "agreements", "", required=False)):
        where = f"agreements[{i}]"
        if not w.keys(row, "agreement", where):
            continue
        name = w.text(row, "name", where)
        if name:
            where = f'agreements[{i}] "{name}"'
        ends = [w.text(row, key, where) for key in ("from", "to")]
        for key, unit_id in zip(("from", "to"), ends):
            if unit_id and unit_id not in units:
                w.add("TMA_UNIT_UNKNOWN", f"{where}.{key}", unit_id)
        if ends[0] and ends[0] == ends[1]:
            w.add("TMA_AGREEMENT_SAME_UNIT", where, name)
        fixes = _check_agreement_fixes(w, row, where)
        departs = _agreement_codes(w.array(row, "departs", where, required=False))
        arrives = _agreement_codes(w.array(row, "arrives", where, required=False))
        if not departs and not arrives:
            w.add("TMA_AGREEMENT_NO_TRAFFIC", where, name)
        levels = [key for key in ("climb", "descent") if key in row]
        if not levels:
            w.add("TMA_AGREEMENT_NO_LEVEL", where, name)
        for key in levels:
            w.level(row[key], f"{where}.{key}")
        priority = row.get("priority")
        if not _is_whole(priority) or priority < 0:
            w.add("TMA_FIELD_SHAPE", f"{where}.priority", "a whole number, 0 or more")
        else:
            runways = _runway_keys(row.get("runways", []))
            origs = departs or ["*"]
            dests = arrives or ["*"]
            tied_reported: set[str] = set()
            for flow_kind in _agreement_flows(departs, arrives, levels):
                for fix_token in fixes:
                    slot = (ends[0], ends[1], flow_kind, fix_token, int(priority))
                    bucket = covered.setdefault(slot, {})
                    for orig in origs:
                        for dest in dests:
                            for (existing_orig, existing_dest), taken in bucket.items():
                                if not _pairs_match(orig, dest, existing_orig, existing_dest):
                                    continue
                                other = _tied_row(taken, runways)
                                if other and other not in tied_reported:
                                    tied_reported.add(other)
                                    w.add("TMA_AGREEMENT_PRIORITY_TIE", where, name, expected=other)
                            taken = bucket.setdefault((orig, dest), {})
                            for runway in runways:
                                taken.setdefault(runway, name)
        if "release_kind" in row:
            w.text(row, "release_kind", where)
        if "holding" in row:
            w.text(row, "holding", where)
        trail = row.get("miles_in_trail", 0)
        if not isinstance(trail, (int, float)) or isinstance(trail, bool) or trail < 0:
            w.add("TMA_FIELD_SHAPE", f"{where}.miles_in_trail", "a number, 0 or more")
        w.array(row, "traffic_of_interest", where, required=False)
        w.array(row, "runways", where, required=False)
        go_around = row.get("go_around")
        if go_around is not None and w.keys(go_around, "go_around", f"{where}.go_around"):
            target = w.text(go_around, "to", f"{where}.go_around")
            if target and target not in units:
                w.add("TMA_UNIT_UNKNOWN", f"{where}.go_around.to", target)
            if "climb" in go_around:
                w.level(go_around["climb"], f"{where}.go_around.climb")


def _departure_without_fix(row: dict) -> bool:
    """A row that only sends traffic away may leave ``fix`` out: it states one level for every
    route leaving that airport, and the hand-off is where the flow leaves the from unit's air,
    which the runtime finds without a fix. An arrival row always names its fix."""
    return "fix" not in row and "departs" in row and "arrives" not in row


def _ancestor_acc_units(bundle_dir: Path) -> list[dict]:
    acc_name = str(RULES.get("acc_file_name", "acc_structure.json"))
    cur = bundle_dir.resolve().parent
    while cur != cur.parent:
        acc_path = cur / acc_name
        if acc_path.is_file():
            try:
                doc = json.loads(acc_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return []
            if isinstance(doc, dict) and isinstance(doc.get("units"), list):
                return [u for u in doc["units"] if isinstance(u, dict)]
            return []
        cur = cur.parent
    return []


def check_bundle(bundle_dir: Path) -> list[str]:
    """Every problem sentence for ``<bundle_dir>/tma_structure.json``, in walk order; empty when absent."""
    path = bundle_dir / RULES["file_name"]
    if not path.is_file():
        return []
    bundle_key = bundle_dir.name
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [Problem("TMA_JSON_INVALID", "").message(bundle_key)]
    coord_name = str(RULES.get("coordination_file_name", "tma_coordination.json"))
    coord_path = bundle_dir / coord_name
    coordination_payload: object = None
    if coord_path.is_file():
        try:
            coordination_payload = json.loads(coord_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            coordination_payload = []
    acc_units = _ancestor_acc_units(bundle_dir)
    problems = check(payload, bundle_key, _sector_ids(bundle_dir), acc_units, coordination_payload)
    problems.extend(_unknown_runway_presets(payload, bundle_dir))
    return [problem.message(bundle_key) for problem in problems]


def _sector_ids(bundle_dir: Path) -> set[str]:
    try:
        document = json.loads((bundle_dir / "sector_definitions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(document, dict):
        return set()
    definitions = airac_overrides.resolve(document, "")
    rows = definitions.get("sector_definitions", definitions.get("definitions", definitions.get("sectors", [])))
    if not isinstance(rows, list):
        return set()
    out: set[str] = set()
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
    return out


def _row_value(row: dict) -> str:
    for key in ("sector_id", "sector", "id", "SECTOR_ID"):
        if key in row:
            return str(row[key])
    return ""


def _unknown_runway_presets(payload: object, bundle_dir: Path) -> list[Problem]:
    """Every runway preset a layout asks for that the airport's runway_configs.json lacks."""
    if not isinstance(payload, dict) or not isinstance(payload.get("layouts"), list):
        return []
    problems: list[Problem] = []
    for index, layout in enumerate(payload["layouts"]):
        if not isinstance(layout, dict) or not isinstance(layout.get("runways"), dict):
            continue
        layout_id = layout.get("id")
        where = f'layouts[{index}] "{layout_id}"' if isinstance(layout_id, str) and layout_id else f"layouts[{index}]"
        for code in sorted(layout["runways"]):
            presets = layout["runways"][code]
            if not ICAO_RE.fullmatch(code) or not isinstance(presets, list):
                continue
            known = _preset_ids(bundle_dir / code)
            for preset in presets:
                if isinstance(preset, str) and preset not in known:
                    problems.append(
                        Problem("TMA_RUNWAY_PRESET_UNKNOWN", f"{where}.runways.{code}", preset, expected=code)
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
