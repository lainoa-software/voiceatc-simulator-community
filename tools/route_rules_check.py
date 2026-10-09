#!/usr/bin/env python3
"""Validate contributor route rules: ROUTES/rules/<ICAO>/<id>.json.

Route rules are the closed-beta tester lane of the website (website ADR 0013,
voiceatc-simulator-web documentation/decisions/0013-route-rules.md). One rule
is one file, written only by the website contribute flow. This tool never edits
those files and builds nothing: the Routes-repo compile job reads them, turns
them into builder facts and writes the gated closed-beta overlay.

This is the port of the website's `src/lib/contribute/route-rules.ts`. The
dangerous direction is the website accepting a rule that this rejects: the
pull request would merge and the next daily release would stop for every data
type. Change a cap or a field here first, then on the website. The website's
`npm run check:route-rules` runs its serialized rules through this tool.

Structural checks only. Whether a fix, airway or STAR exists in the current
cycle is the compile job's check, which suspends a rule instead of failing the
release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = Path("ROUTES") / "rules"

SCHEMA_VERSION = 1
KINDS = ("arrivals", "departures", "between")
ACTIONS = ("direct", "use", "entry", "exit", "prefer")
MANDATORY = ("direct", "use", "entry", "exit")

MAX_RULE_AIRPORTS = 200
MAX_RULE_FIXES = 8
MAX_SEQUENCE_TOKENS = 41
MAX_DOCUMENT_CHARS = 160
MAX_URL_CHARS = 500
MAX_QUOTE_CHARS = 600
MIN_SOURCE_CHARS = 3

ICAO_RE = re.compile(r"^[A-Z0-9]{4}$")
FIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,4}$")
AIRWAY_RE = re.compile(r"^[A-Z]{1,3}[0-9]{1,4}[A-Z]?$")
RULE_ID_RE = re.compile(r"^[0-9a-f]{8}$")
AIRAC_RE = re.compile(r"^[0-9]{4}$")
CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
URL_RE = re.compile(r"^https://[^\s]+\.[^\s]+$")

# Body keys in the order the website writes them; `id`, `created_at` and
# `creation_airac` frame the body and are not part of the identity hash.
BODY_KEYS = (
    "airport", "flights", "other_airport", "origins", "destinations", "on_airway", "at_fix",
    "action", "value", "star_from", "sid_to", "source",
)
TOKEN_KEYS = ("airport", "other_airport", "origins", "destinations", "on_airway", "at_fix", "value", "star_from", "sid_to")
ALLOWED_KEYS = {"schema_version", "id", "created_at", "creation_airac", *BODY_KEYS}
SOURCE_KEYS = ("document", "url", "quote")


def js_length(value: str) -> int:
    """String length as JavaScript counts it (UTF-16 code units), so the caps agree with the website."""
    return len(value.encode("utf-16-le")) // 2


def normalize_tokens(value: str) -> str:
    return " ".join(value.upper().split())


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def rule_id(rule: dict) -> str:
    """First 8 hex of SHA-256 over the canonical body, as the website computes it.

    The website hashes `JSON.stringify(body)`: compact, keys in BODY_KEYS order,
    absent keys left out, non-ASCII unescaped. `json.dumps` with these options
    produces the same bytes.
    """
    body = {key: rule[key] for key in BODY_KEYS if key in rule}
    if "source" in body:
        body["source"] = {key: body["source"][key] for key in SOURCE_KEYS}
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _airport_list(raw: str, airport: str, errors: list[str]) -> None:
    items = raw.split(" ")
    if len(items) > MAX_RULE_AIRPORTS:
        errors.append(f"a rule can have a maximum of {MAX_RULE_AIRPORTS} airports")
    bad = next((icao for icao in items if not ICAO_RE.fullmatch(icao)), None)
    if bad:
        errors.append(f"'{bad}' is not an ICAO code")
    if airport in items:
        errors.append(f"{airport} is in its own airport list")
    if len(set(items)) != len(items):
        errors.append("an airport is in the list more than one time")


def _fix_list(raw: str, errors: list[str]) -> None:
    items = raw.split(" ")
    if len(items) > MAX_RULE_FIXES:
        errors.append(f"a maximum of {MAX_RULE_FIXES} fixes")
    bad = next((fix for fix in items if not FIX_RE.fullmatch(fix)), None)
    if bad:
        errors.append(f"'{bad}' is not a fix")
    if len(set(items)) != len(items):
        errors.append("a fix is in the list more than one time")


def sequence_errors(raw: str) -> list[str]:
    tokens = raw.split(" ") if raw else []
    if len(tokens) < 3:
        return ["a sequence is a fix, an airway or DCT, and a fix"]
    if len(tokens) > MAX_SEQUENCE_TOKENS:
        return [f"a sequence has a maximum of {MAX_SEQUENCE_TOKENS} items"]
    if len(tokens) % 2 == 0:
        return ["a sequence starts and ends with a fix"]
    for index, token in enumerate(tokens):
        if index % 2 == 0 and not FIX_RE.fullmatch(token):
            return [f"'{token}' is not a fix"]
        if index % 2 == 1 and token != "DCT" and not AIRWAY_RE.fullmatch(token):
            return [f"'{token}' is not an airway or DCT"]
    return []


def validate_rule(rule: object, folder_icao: str, file_stem: str) -> list[str]:
    """Every problem with one parsed rule file. Empty means valid."""
    if not isinstance(rule, dict):
        return ["the file is not a JSON object"]
    errors: list[str] = []

    unknown = sorted(set(rule) - ALLOWED_KEYS)
    if unknown:
        errors.append(f"unknown keys: {', '.join(unknown)}")
    if rule.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    for key in TOKEN_KEYS:
        value = rule.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            errors.append(f"{key} must be a non-empty string when present")
        elif value != normalize_tokens(value):
            errors.append(f"{key} is not normalized (uppercase, single spaces)")
    if errors:
        return errors

    airport = rule.get("airport", "")
    flights = rule.get("flights")
    action = rule.get("action")
    value = rule.get("value", "")

    if not ICAO_RE.fullmatch(airport):
        errors.append("airport must be an ICAO code")
    elif airport != folder_icao:
        errors.append(f"airport {airport} is not the folder {folder_icao}")
    if flights not in KINDS:
        errors.append(f"flights must be one of {', '.join(KINDS)}")

    other = rule.get("other_airport")
    if flights == "between":
        if not other or not ICAO_RE.fullmatch(other):
            errors.append("a between rule needs other_airport")
        elif other == airport:
            errors.append("other_airport must be different from airport")
    elif other:
        errors.append("only a between rule has other_airport")

    if "origins" in rule:
        if flights != "arrivals":
            errors.append("only arrivals have origins")
        else:
            _airport_list(rule["origins"], airport, errors)
    if "destinations" in rule:
        if flights != "departures":
            errors.append("only departures have destinations")
        else:
            _airport_list(rule["destinations"], airport, errors)

    on_airway = rule.get("on_airway")
    at_fix = rule.get("at_fix")
    if bool(on_airway) != bool(at_fix):
        errors.append("on_airway and at_fix go together")
    if on_airway and not AIRWAY_RE.fullmatch(on_airway):
        errors.append(f"'{on_airway}' is not an airway")
    if at_fix and not FIX_RE.fullmatch(at_fix):
        errors.append(f"'{at_fix}' is not a fix")

    if action not in ACTIONS:
        errors.append(f"action must be one of {', '.join(ACTIONS)}")
    elif not value:
        errors.append("value is required")
    elif action == "direct":
        if not FIX_RE.fullmatch(value):
            errors.append(f"'{value}' is not a fix")
        elif value == at_fix:
            errors.append("the direct fix must be different from at_fix")
    elif action in ("use", "prefer"):
        errors.extend(sequence_errors(value))
    else:
        if action == "entry" and flights != "arrivals":
            errors.append("only arrivals have entry fixes")
        if action == "exit" and flights != "departures":
            errors.append("only departures have exit fixes")
        _fix_list(value, errors)

    star_from = rule.get("star_from")
    if star_from:
        if flights != "arrivals":
            errors.append("only arrivals fly a STAR")
        elif not FIX_RE.fullmatch(star_from):
            errors.append(f"'{star_from}' is not a fix")
        elif action == "direct" and value and value != star_from:
            errors.append(f"the STAR must start at the direct fix {value}")
    sid_to = rule.get("sid_to")
    if sid_to:
        if flights != "departures":
            errors.append("only departures fly a SID")
        elif not FIX_RE.fullmatch(sid_to):
            errors.append(f"'{sid_to}' is not a fix")

    source = rule.get("source")
    if source is None:
        if action in MANDATORY:
            errors.append("a must rule needs a source")
    elif not isinstance(source, dict) or set(source) != set(SOURCE_KEYS):
        errors.append("source must have exactly document, url and quote")
    elif not all(isinstance(source[key], str) for key in SOURCE_KEYS):
        errors.append("source fields must be strings")
    else:
        document, url, quote = source["document"], source["url"], source["quote"]
        if document != normalize_text(document) or quote != normalize_text(quote) or url != url.strip():
            errors.append("source text is not normalized (trimmed, single spaces)")
        if not MIN_SOURCE_CHARS <= js_length(document) <= MAX_DOCUMENT_CHARS:
            errors.append("source.document length is out of range")
        if not URL_RE.fullmatch(url) or js_length(url) > MAX_URL_CHARS:
            errors.append("source.url must be an https link")
        if not MIN_SOURCE_CHARS <= js_length(quote) <= MAX_QUOTE_CHARS:
            errors.append("source.quote length is out of range")

    if not CREATED_AT_RE.fullmatch(str(rule.get("created_at", ""))):
        errors.append("created_at must be YYYY-MM-DDTHH:MM:SSZ")
    if not AIRAC_RE.fullmatch(str(rule.get("creation_airac", ""))):
        errors.append("creation_airac must be a four-digit AIRAC cycle")

    rid = rule.get("id")
    if not isinstance(rid, str) or not RULE_ID_RE.fullmatch(rid):
        errors.append("id must be 8 lowercase hex")
    elif rid != file_stem:
        errors.append(f"id {rid} is not the file name {file_stem}")
    elif not errors and rid != rule_id(rule):
        errors.append(f"id {rid} is not the hash of the rule ({rule_id(rule)})")
    return errors


def validate_tree(root: Path) -> list[str]:
    """Problems across every rule file, as `path: problem` lines."""
    base = root / RULES_DIR
    if not base.exists():
        return []
    problems: list[str] = []
    for path in sorted(base.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(base).parts
        if parts == ("README.md",):
            continue
        if len(parts) != 2 or path.suffix != ".json" or not ICAO_RE.fullmatch(parts[0]):
            problems.append(f"{relative}: rule files are ROUTES/rules/<ICAO>/<id>.json")
            continue
        try:
            rule = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            problems.append(f"{relative}: not valid JSON ({error})")
            continue
        problems.extend(f"{relative}: {error}" for error in validate_rule(rule, parts[0], path.stem))
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate ROUTES/rules/<ICAO>/<id>.json route rule files.")
    parser.add_argument("--validate-only", action="store_true", help="Validate the rule files (the only mode)")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root to validate (default: this one)")
    args = parser.parse_args()

    problems = validate_tree(args.root)
    count = len(list((args.root / RULES_DIR).glob("*/*.json")))
    if problems:
        for problem in problems:
            print(f"ERROR {problem}", file=sys.stderr)
        print(f"{len(problems)} route rule problems in {count} files", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {count} route rule files")


if __name__ == "__main__":
    main()
