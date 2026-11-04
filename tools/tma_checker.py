"""Reference checker for tma.json, schema 1. Rules and messages come from tma_rules.json.

check(payload, bundle_key, sector_ids) returns every problem as a Problem(code, where, value,
expected, allowed), in the order the walk below meets them. Both game and community checkers must
produce the same (code, where) list for every case in tma_cases/cases.json.
"""
from __future__ import annotations

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
FREQ_RE = re.compile(r"^\d{3}\.\d{3}$")
LEVEL_RE = re.compile(r"^[FA]\d{3}$")

KEYS = {
    "root": {"schema", "tma", "airports", "units", "layouts", "agreements"},
    "tma": {"id", "name"},
    "unit": {"id", "call_sign", "services", "airport", "frequencies"},
    "layout": {"id", "runways", "positions"},
    "position": {"sector", "name", "unit", "frequency", "airports"},
    "agreement": {"name", "from", "to", "departs", "arrives", "fix", "climb", "descent", "priority",
                  "release_kind", "miles_in_trail", "go_around", "traffic_of_interest", "holding"},
    "go_around": {"to", "climb"},
}


@dataclass(frozen=True)
class Problem:
    code: str
    where: str
    value: str = ""
    expected: str = ""
    allowed: str = ""

    def message(self, bundle_key: str) -> str:
        where = f"{bundle_key}/{RULES['file_name']} {self.where}".strip()
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
    return json.dumps(value)


class _Walk:
    def __init__(self, bundle_key: str, sector_ids: set[str]) -> None:
        self.bundle_key = bundle_key
        self.sector_ids = sector_ids
        self.problems: list[Problem] = []

    def add(self, code: str, where: str, value: object = "", expected: str = "", allowed: str = "") -> None:
        self.problems.append(Problem(code, where, _text(value), expected, allowed))

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


def check(payload: object, bundle_key: str, sector_ids: set[str]) -> list[Problem]:
    w = _Walk(bundle_key, sector_ids)
    if not isinstance(payload, dict):
        w.add("TMA_JSON_INVALID", "")
        return w.problems
    if "schema" not in payload:
        w.add("TMA_SCHEMA_MISSING", "schema")
        return w.problems
    schema = payload["schema"]
    if not _is_whole(schema) or schema < 1:
        w.add("TMA_FIELD_SHAPE", "schema", "a whole number")
        return w.problems
    if schema > RULES["schema"]:
        w.add("TMA_SCHEMA_NEWER", "schema", schema)
        return w.problems
    w.keys(payload, "root", "")
    _tma(w, payload)
    airports = _airports(w, payload)
    units = _units(w, payload, airports)
    _layouts(w, payload, airports, units)
    _agreements(w, payload, units)
    return w.problems


def _tma(w: _Walk, payload: dict) -> None:
    if "tma" not in payload:
        w.add("TMA_FIELD_MISSING", "", "tma")
        return
    tma = payload["tma"]
    if w.keys(tma, "tma", "tma"):
        tma_id = w.text(tma, "id", "tma")
        w.text(tma, "name", "tma")
        if tma_id and tma_id != w.bundle_key:
            w.add("TMA_ID_MISMATCH", "tma.id", tma_id, expected=w.bundle_key)


def _airports(w: _Walk, payload: dict) -> list[str]:
    result: list[str] = []
    for i, code in enumerate(w.array(payload, "airports", "")):
        where = f"airports[{i}]"
        if not isinstance(code, str) or not ICAO_RE.match(code):
            w.add("TMA_AIRPORT_INVALID", where, code)
        elif code in result:
            w.add("TMA_ID_DUPLICATE", where, code)
        else:
            result.append(code)
    return result


def _units(w: _Walk, payload: dict, airports: list[str]) -> dict[str, dict]:
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
        needing = [name for name in services if SERVICES[name]["needs_airport"]]
        if needing and "airport" not in unit:
            w.add("TMA_UNIT_AIRPORT_MISSING", where, needing[0])
        if "airport" in unit and unit["airport"] not in airports:
            w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.airport", unit["airport"])
        frequencies = [w.frequency(f, f"{where}.frequencies[{j}]")
                       for j, f in enumerate(w.array(unit, "frequencies", where))]
        if unit_id and unit_id not in units:
            units[unit_id] = {"services": services, "frequencies": set(frequencies)}
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


def _layouts(w: _Walk, payload: dict, airports: list[str], units: dict[str, dict]) -> None:
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
        _runways(w, layout, where, airports)
        owners: dict[str, int] = {code: 0 for code in airports}
        sectors: set[str] = set()
        for k, position in enumerate(w.array(layout, "positions", where)):
            _position(w, position, f"{where}.positions[{k}]", units, owners, sectors)
        for code in airports:
            if owners[code] == 0:
                w.add("TMA_AIRPORT_NO_OWNER", where, code)
            elif owners[code] > 1:
                w.add("TMA_AIRPORT_TWO_OWNERS", where, code)


def _runways(w: _Walk, layout: dict, where: str, airports: list[str]) -> None:
    if "runways" not in layout:
        return
    runways = layout["runways"]
    if not isinstance(runways, dict) or not runways:
        w.add("TMA_FIELD_SHAPE", f"{where}.runways", "an object of airport to runway preset ids")
        return
    for code in sorted(runways):
        if code not in airports:
            w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.runways", code)
        presets = runways[code]
        if not isinstance(presets, list) or not presets or not all(isinstance(p, str) and p.strip() for p in presets):
            w.add("TMA_FIELD_SHAPE", f"{where}.runways.{code}", "a non-empty array of runway preset ids")


def _position(w: _Walk, position: object, where: str, units: dict[str, dict],
              owners: dict[str, int], sectors: set[str]) -> None:
    if not w.keys(position, "position", where):
        return
    _position_sector(w, position, where, sectors)
    if "name" not in position:
        w.add("TMA_FIELD_MISSING", where, "name")
    elif not isinstance(position["name"], str) or not NAME_RE.match(position["name"]):
        w.add("TMA_POSITION_NAME", f"{where}.name", position["name"])
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
    for m, code in enumerate(w.array(position, "airports", where)):
        if isinstance(code, str) and code in owners:
            owners[code] += 1
        else:
            w.add("TMA_AIRPORT_NOT_IN_TMA", f"{where}.airports[{m}]", code)


def _position_sector(w: _Walk, position: dict, where: str, sectors: set[str]) -> None:
    if "sector" not in position:
        w.add("TMA_FIELD_MISSING", where, "sector")
        return
    sector = position["sector"]
    if not isinstance(sector, str) or not SECTOR_RE.match(sector):
        w.add("TMA_POSITION_ONE_SECTOR", f"{where}.sector", sector)
    elif sector not in w.sector_ids:
        w.add("TMA_SECTOR_UNDEFINED", f"{where}.sector", sector)
    elif sector in sectors:
        w.add("TMA_SECTOR_TWICE", f"{where}.sector", sector)
    else:
        sectors.add(sector)


def _agreements(w: _Walk, payload: dict, units: dict[str, dict]) -> None:
    covered: dict[tuple, str] = {}
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
        fix = w.text(row, "fix", where)
        traffic = [(key, code) for key in ("departs", "arrives") for code in w.array(row, key, where, required=False)]
        if not traffic:
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
            for key, code in traffic:
                slot = (ends[0], ends[1], key, str(code), fix, int(priority))
                if slot in covered:
                    w.add("TMA_AGREEMENT_PRIORITY_TIE", where, name, expected=covered[slot])
                covered.setdefault(slot, name)
        if "release_kind" in row:
            w.text(row, "release_kind", where)
        if "holding" in row:
            w.text(row, "holding", where)
        trail = row.get("miles_in_trail", 0)
        if not isinstance(trail, (int, float)) or isinstance(trail, bool) or trail < 0:
            w.add("TMA_FIELD_SHAPE", f"{where}.miles_in_trail", "a number, 0 or more")
        w.array(row, "traffic_of_interest", where, required=False)
        go_around = row.get("go_around")
        if go_around is not None and w.keys(go_around, "go_around", f"{where}.go_around"):
            target = w.text(go_around, "to", f"{where}.go_around")
            if target and target not in units:
                w.add("TMA_UNIT_UNKNOWN", f"{where}.go_around.to", target)
            if "climb" in go_around:
                w.level(go_around["climb"], f"{where}.go_around.climb")
