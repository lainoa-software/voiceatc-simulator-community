#!/usr/bin/env python3
"""Schema-3 airspace features that a released checker does not know, and how to drop them.

A bundle that uses nothing new keeps the single schema-3 entry it has always had, byte
for byte. A bundle that does use something new ships two entries with the same id: the
first (the one an older build takes) holds the downgraded rows and the ``requires`` it
had before, the last holds the authored bytes and the capabilities they need. The rules
live here, pure: no file access, so every decision is testable from documents alone.

The shapes are the ones the game already reads: a layout's ``configurations`` maps unit
-> configuration -> position -> sectors, and a sector's ``made_of`` lists the children it
is cut into.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Callable, Mapping, Sequence

AGREEMENT_END_KEYS = ("from", "to")
GO_AROUND_KEY = "go_around"
GO_AROUND_END_KEY = "to"
SECTOR_END_CAPABILITY = "community.agreement_sector_ends"


@dataclass(frozen=True)
class AirspaceContext:
    """The airspace names one bundle's own files and its ancestor ACC define.

    ``bundle`` is the bundle path, used only to name it in an error. ``known_units`` and
    ``known_positions`` are what a released checker accepts for this bundle; everything
    else it finds in the files is kept so a later feature can resolve through it.
    """

    bundle: str = ""
    known_units: frozenset[str] = frozenset()
    known_positions: frozenset[str] = frozenset()
    sectors: frozenset[str] = frozenset()
    sector_position: Mapping[str, str] = field(default_factory=dict)
    top_center: str = ""
    all_units: frozenset[str] = frozenset()
    all_positions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Feature:
    """One thing a released checker does not know, and the rows that no longer use it."""

    capability: str
    used_by: Callable[[Sequence[dict[str, object]], AirspaceContext], bool]
    downgrade: Callable[[Sequence[dict[str, object]], AirspaceContext], list[dict[str, object]]]


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _document(payload: object) -> Mapping[str, object]:
    return payload if isinstance(payload, Mapping) else {}


def _unit_ids(payload: object) -> set[str]:
    units = _document(payload).get("units")
    if not isinstance(units, list):
        return set()
    return {_text(unit.get("id")) for unit in units if isinstance(unit, dict) and _text(unit.get("id"))}


def _call_signs(payload: object) -> set[str]:
    positions = _document(payload).get("positions")
    if not isinstance(positions, list):
        return set()
    return {
        _text(position.get("call_sign"))
        for position in positions
        if isinstance(position, dict) and _text(position.get("call_sign"))
    }


def _sector_catalog(*payloads: object) -> dict[str, dict]:
    """``sectors.<id>`` from every document that has one, the first definition winning."""
    catalog: dict[str, dict] = {}
    for payload in payloads:
        sectors = _document(payload).get("sectors")
        if not isinstance(sectors, dict):
            continue
        for key, value in sectors.items():
            sector_id = _text(key).upper()
            if sector_id and sector_id not in catalog:
                catalog[sector_id] = value if isinstance(value, dict) else {}
    return catalog


def _expanded(sector_ids: object, catalog: Mapping[str, dict]) -> frozenset[str]:
    """``made_of`` walked to its leaves, as the game does."""
    leaves: list[str] = []

    def walk(sector_id: str, visiting: set[str]) -> None:
        if not sector_id or sector_id in visiting:
            return
        visiting.add(sector_id)
        children = catalog.get(sector_id, {}).get("made_of")
        if isinstance(children, list) and children:
            for child in children:
                walk(_text(child).upper(), visiting)
        elif sector_id not in leaves:
            leaves.append(sector_id)

    for sector_id in sector_ids if isinstance(sector_ids, list) else []:
        walk(_text(sector_id).upper(), set())
    return frozenset(leaves)


def _first_wins(base: dict, other: dict) -> dict:
    """``other``'s entries added under ``base``'s, which wins wherever both name one leaf."""
    merged = dict(base)
    for key, value in other.items():
        if key not in merged:
            merged[key] = value
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _first_wins(merged[key], value)
    return merged


def with_every_tier(document: object) -> dict[str, object]:
    """One document with every AIRAC tier folded in, the base tier first and winning.

    The game knows a name a later tier introduces; a released checker reads one tier at a
    time, so where tiers disagree the base tier's definition is the one kept.
    """
    merged: dict[str, object] = {}
    for tier in _tier_documents(document):
        for key, value in tier.items():
            if key == "airac_overrides":
                continue
            current = merged.get(key)
            if key not in merged:
                merged[key] = value
            elif isinstance(current, list) and isinstance(value, list):
                merged[key] = [*current, *value]
            elif isinstance(current, dict) and isinstance(value, dict):
                merged[key] = _first_wins(current, value)
    return merged


def _configurations(*layouts: object) -> dict[str, dict]:
    """Unit -> its configurations, the first layout that names the unit winning."""
    merged: dict[str, dict] = {}
    for layout in layouts:
        configurations = _document(layout).get("configurations")
        if not isinstance(configurations, dict):
            continue
        for unit, unit_configurations in configurations.items():
            unit_id = _text(unit)
            if unit_id and unit_id not in merged and isinstance(unit_configurations, dict):
                merged[unit_id] = unit_configurations
    return merged


def _top_center(payload: object) -> str:
    """The ACC unit every other one is ``part_of``: its first root with a centre service."""
    units = _document(payload).get("units")
    if not isinstance(units, list):
        return ""
    root = ""
    for unit in units:
        if not isinstance(unit, dict):
            continue
        unit_id = _text(unit.get("id"))
        if not unit_id or _text(unit.get("part_of")):
            continue
        services = unit.get("services")
        names = {_text(name) for name in services} if isinstance(services, list) else set()
        if "center" in names:
            return unit_id
        root = root or unit_id
    return root


def airspace_context(
    bundle_documents: Mapping[str, object],
    acc_documents: Mapping[str, object] | None = None,
    *,
    bundle: str = "",
) -> AirspaceContext:
    """Read one bundle's documents (and its ancestor ACC's) into the names they define."""
    own = {kind: with_every_tier(payload) for kind, payload in dict(bundle_documents or {}).items()}
    acc = {kind: with_every_tier(payload) for kind, payload in dict(acc_documents or {}).items()}
    catalog = _sector_catalog(own.get("definitions"), acc.get("definitions"))
    known_units = (
        _unit_ids(own.get("tma_definitions"))
        | _unit_ids(own.get("acc_definitions"))
        | _unit_ids(acc.get("acc_definitions"))
    )
    known_positions = (
        _call_signs(own.get("tma_definitions"))
        | _call_signs(own.get("acc_definitions"))
        | _call_signs(acc.get("acc_definitions"))
    )

    worked_by: list[tuple[str, frozenset[str]]] = []
    configurations = _configurations(
        own.get("tma_layout"), own.get("acc_layout"), acc.get("acc_layout")
    )
    for unit_configurations in configurations.values():
        for configuration in unit_configurations.values():
            positions = _document(configuration).get("positions")
            if not isinstance(positions, dict):
                continue
            for call_sign, raw_sectors in positions.items():
                position = _text(call_sign).upper()
                if not position:
                    continue
                worked = _expanded(raw_sectors, catalog)
                worked_by.append((position, worked))

    # A sector is worked by the first position, in unit then configuration then position
    # order, whose own sectors reach it (a composite sector end reaches its children, and a
    # position claiming a composite reaches every child of it).
    sector_position: dict[str, str] = {}
    for sector_id in catalog:
        wanted = _expanded([sector_id], catalog) | {sector_id}
        for position, worked in worked_by:
            if worked & wanted:
                sector_position[sector_id] = position
                break

    all_positions = known_positions | {position for position, _worked in worked_by}
    return AirspaceContext(
        bundle=bundle,
        known_units=frozenset(known_units),
        known_positions=frozenset(known_positions),
        sectors=frozenset(catalog),
        sector_position=sector_position,
        top_center=_top_center(acc.get("acc_definitions") or own.get("acc_definitions")),
        all_units=frozenset(known_units | set(configurations)),
        all_positions=frozenset(all_positions),
    )


def agreement_ends(row: object) -> tuple[str, ...]:
    """The names a row hands airspace to: ``from``, ``to`` and the go-around's ``to``."""
    if not isinstance(row, Mapping):
        return ()
    ends = [text for text in (_text(row.get(key)) for key in AGREEMENT_END_KEYS) if text]
    go_around = row.get(GO_AROUND_KEY)
    if isinstance(go_around, dict):
        end = _text(go_around.get(GO_AROUND_END_KEY))
        if end:
            ends.append(end)
    return tuple(ends)


def agreement_rows(document: object) -> list[dict[str, object]]:
    """Every agreement row of a coordination document, its AIRAC variants included."""
    rows: list[dict[str, object]] = []
    for tier_document in _tier_documents(document):
        tier_rows = tier_document.get("agreements")
        if isinstance(tier_rows, list):
            rows.extend(row for row in tier_rows if isinstance(row, dict))
    return rows


def _tier_documents(document: object) -> list[Mapping[str, object]]:
    root = _document(document)
    documents = [root]
    overrides = root.get("airac_overrides")
    if isinstance(overrides, dict):
        documents.extend(value for value in overrides.values() if isinstance(value, dict))
    return documents


def is_sector_end(name: str, context: AirspaceContext) -> bool:
    """True when an agreement end names a sector where a released checker wants a unit.

    A seat that carries its sector's code is a position every released checker knows.
    """
    return name in context.sectors and not (
        name in context.known_units or name in context.known_positions
    )


def _sector_ends_used(rows: Sequence[dict[str, object]], context: AirspaceContext) -> bool:
    return any(is_sector_end(end, context) for row in rows for end in agreement_ends(row))


def _downgrade_sector_ends(
    rows: Sequence[dict[str, object]], context: AirspaceContext
) -> list[dict[str, object]]:
    """Replace each sector end by the position that works it; drop a row nobody works."""
    downgraded: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            downgraded.append(row)
            continue
        result = deepcopy(row)
        source_from, source_to = _text(row.get("from")), _text(row.get("to"))
        dropped = False
        for key in AGREEMENT_END_KEYS:
            end = _text(result.get(key))
            if not is_sector_end(end, context):
                continue
            position = context.sector_position.get(end, "")
            if not position:
                dropped = True
                break
            result[key] = position
        if dropped:
            continue
        start, end = _text(result.get("from")), _text(result.get("to"))
        # Two sectors one position works both land on one name, which a released checker
        # refuses (TMA_AGREEMENT_SAME_UNIT); a row that already had equal ends is left alone.
        if start and start == end and source_from != source_to:
            continue
        go_around = result.get(GO_AROUND_KEY)
        if isinstance(go_around, dict):
            end = _text(go_around.get(GO_AROUND_END_KEY))
            if is_sector_end(end, context):
                position = context.sector_position.get(end, "")
                if not position:
                    continue
                result[GO_AROUND_KEY] = {**go_around, GO_AROUND_END_KEY: position}
        downgraded.append(result)
    return downgraded


FEATURES: tuple[Feature, ...] = (
    Feature(SECTOR_END_CAPABILITY, _sector_ends_used, _downgrade_sector_ends),
)


def used_capabilities(
    rows: Sequence[dict[str, object]], context: AirspaceContext
) -> tuple[str, ...]:
    """The capabilities these rows use, in ``FEATURES`` order."""
    return tuple(feature.capability for feature in FEATURES if feature.used_by(rows, context))


def downgrade_rows(
    rows: Sequence[dict[str, object]],
    context: AirspaceContext,
) -> list[dict[str, object]]:
    """Every feature's downgrade in order, duplicates collapsed, unknown ends refused."""
    result: list[dict[str, object]] = [deepcopy(row) for row in rows]
    for feature in FEATURES:
        result = feature.downgrade(result, context)

    kept: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in result:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        # Identical in every key, or identical except its name: the first one names it.
        key = json.dumps({k: v for k, v in row.items() if k != "name"}, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)

    for row in kept:
        for end in agreement_ends(row):
            if end in context.known_units or end in context.known_positions:
                continue
            raise ValueError(
                f"{context.bundle or 'bundle'}: agreement {_text(_document(row).get('name'))!r}"
                f" ends at {end!r}, which no released checker knows"
            )
    return kept


def downgrade_document(document: object, context: AirspaceContext) -> dict[str, object]:
    """A copy of a coordination document with every agreements list downgraded."""
    result = deepcopy(_document(document))
    for tier_document in _tier_documents(result):
        rows = tier_document.get("agreements")
        if isinstance(rows, list):
            tier_document["agreements"] = downgrade_rows(rows, context)
    return result
