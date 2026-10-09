# Route rules

Contributor route rules, written by the VoiceATC Simulator website's
closed-beta tester lane (`/contribute/route-rules`). A rule tells the route
generator which routes the flights use at one airport, for example:

> Arrivals into WSSS on A464 at ARAMA must fly direct to TEBUN, then fly the
> STAR that starts at TEBUN.

The website is the only writer of this tree, and every rule reaches `main`
through maintainer review. Nothing in the daily release reads these files: the
Routes-repo compile job turns accepted rules into builder facts, rebuilds only
the routes they touch, and publishes the result as a route overlay that only
the closed-beta channel receives. The generated tables are never edited.

## Layout

```
ROUTES/rules/{ICAO}/{id}.json      one rule per file
```

`{ICAO}` is the airport of the rule's Flights block. One file per rule, so two
contributors adding rules to the same airport never touch the same file, and
removing a rule deletes its file.

```json
{
  "schema_version": 1,
  "id": "eec26c79",
  "airport": "WSSS",
  "flights": "arrivals",
  "on_airway": "A464",
  "at_fix": "ARAMA",
  "action": "direct",
  "value": "TEBUN",
  "star_from": "TEBUN",
  "source": {
    "document": "AIP Singapore AD 2 WSSS 19.2.1",
    "url": "https://aim-sg.caas.gov.sg/",
    "quote": "Arrivals into Changi to flight plan via A464 - ARAMA – TEBUN. After TEBUN, to join the TEBUN STAR."
  },
  "created_at": "2026-10-09T13:00:00Z",
  "creation_airac": "2610"
}
```

| Field | Meaning |
|---|---|
| `flights` | `arrivals` into `airport`, `departures` from it, or `between` `airport` and `other_airport` (both directions) |
| `origins` / `destinations` | Arrivals / departures only. Space-separated ICAOs. Absent means all |
| `on_airway`, `at_fix` | The flights are on this airway at this fix. Both or neither |
| `action` | `direct` (one fix), `use` (a `FIX AIRWAY FIX …` sequence), `entry` / `exit` (fix lists, arrivals / departures) are **must** rules. `prefer` (a sequence) is a **should** rule |
| `star_from` | Arrivals: the STAR that starts at this fix. STARs are named by entry fix, so a renumbered STAR still matches |
| `sid_to` | Departures: the SID to this fix |
| `source` | Required for every must rule: the document, an https link, and the quoted instruction |

- `id` is the first 8 hex characters of the SHA-256 of the compact JSON of the
  body (every key except `schema_version`, `id`, `created_at` and
  `creation_airac`, in the order above). The same rule sent twice is one file.
- Lists are space-separated strings, never JSON arrays, so the website's bytes
  are already the prettier format of this repository.
- Rule files are anonymous, like player routes: no author key.

`python tools/route_rules_check.py --validate-only` checks the shape in every
pull request and before every release. Whether a fix, airway or STAR exists in
the current AIRAC cycle is the compile job's check: a rule that does not
resolve is suspended and its routes fall back to the generated ones. It is
never a release failure.

The website's copy of these checks is `src/lib/contribute/route-rules.ts` in
`voiceatc-simulator-web` (ADR 0013). Change a cap or a field here first.
