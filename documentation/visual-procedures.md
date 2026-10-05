# Charted visual procedures

Contributor workflow: [Visual Procedures](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Visual-Procedures).
This page owns the detailed schema, evidence contract and maintainer review checklist.

`visual_procedures.json` contains named, charted IFR visual approaches for one
airport. It is community data consumed by the simulator's 0.6.2 visual-
approach catalog. A generic visual approach is a simulator capability and does
not belong in this repository.

## Placement and one-file rule

Put the file in the airport folder already registered in
[`content_hierarchy.json`](content_hierarchy.json):

```text
Region / [Nationality] / FIR-or-ARTCC / [ACC] / Terminal / ICAO /
visual_procedures.json
```

There must be at most one visual-procedure file for an ICAO airport. Multiple
named procedures and multiple runway variants belong in that file. Do not add a
new terminal scope only to hold a visual procedure; use
`python tools/content_hierarchy.py --register <scope>` when the airport itself
is new.

## Schema

The top level is exactly:

```json
{
  "schema_version": 1,
  "airport": "KDCA",
  "procedures": []
}
```

Each procedure has an uppercase stable `id`, published `name`, at most eight
spoken `aliases`, `classification: "charted_ifr_visual"`, a `policy_profile`
(`FAA` or `ICAO`), `source`, and one or more `variants`. The source must name
the authority and chart, provide an HTTPS URL, an effective date or AIRAC
cycle, and the date it was checked. Do not publish an `availability` object:
ceiling, visibility, daylight, tower, and free-form note fields are retired
because the simulator does not consume them. The validator rejects that legacy
property while the official source citation remains mandatory.

Each variant has a stable `id`, an exact zero-padded `runway` (`01`–`36`, with
optional `L`, `C`, or `R`), a `clearance_name`, `entry_point_id`,
`sight_reference_point_id`, and an ordered `legs` array. The entry must be the
first leg, and the sight reference must identify one of the legs. Each leg has
an `id`, display `name`, `path_term` (`TF`, `CF`, `RF`, or `AF`), latitude,
longitude, and `fly_over`. `CF` legs require `course_deg`; `RF` and `AF` legs
require `arc_center`, `arc_radius_nm`, and `turn_direction`. Optional altitude
and speed constraints use `status: "required"` or `"recommended"` and are
checked by the simulator accordingly. A published altitude window uses
`kind: "between"`, `value_ft` for the lower bound, and `value2_ft` for the
upper bound; do not discard either mandatory limit.

Two optional fields refine how a published route is acquired without breaking
existing files. `join_policy` is `entry_required` by default; use
`forward_route` only when the published procedure permits joining an already
established route instead of flying back to its first authored anchor. The
simulator selects the earliest forward TF/CF segment that does not reverse the
published route or cross protected airspace; it never joins an RF/AF arc in the
middle. `sight_reference` contains a spoken `name`, up to eight `aliases`, and
`scope: "point" | "route"`. Point scope uses the existing sight-reference leg.
Route scope means the crew identifies the authored route ahead—such as "the
river"—rather than claiming a feeder fix is the visual landmark. The required
entry and sight point IDs remain stable anchors in both cases. These fields are
the schema-v1 compatibility cue for older clients. New clients expose a named
variant only when its independently sourced sight-reference sidecar is also
available; they never turn this display label into sight geometry.

An optional `final` object may provide `course_deg` and `glidepath_deg`. Do not
write a runway threshold, missed approach, `approach_visual_segment`, contact
approach, circling route, or VFR/AFIS landing route into this schema. The game
resolves the threshold from navdata. When the same official chart publishes a
go-around, author it in the separate additive sidecar described below.

An RF or AF leg cannot be the first leg. Its preceding point and endpoint must
both lie on the declared radius within the validator's small chart-tracing
tolerance; author a straight leg to the arc join before the curved leg. The
authored direction must produce a sweep of at most 300 degrees. This guard
catches a reversed `turn_direction` before the simulator can treat an
unsupported long arc as a straight chord.

The validator rejects unknown keys, duplicate IDs or spoken names, invalid
coordinates, malformed leg geometry, missing source/entry/sight evidence,
files over 256 KiB, more than 64 procedures, or more than 128 legs per variant.
Geometry beyond 40 NM from the entry is a review advisory; beyond 100 NM is a
hard error. Runway existence is checked against playable navdata by the game
review tooling; this repository validator checks identifier shape and airport
placement because navdata is not shipped here.

## Published sight references

`visual_sight_references.json` is an optional sibling of
`visual_procedures.json`. It gives each playable named variant one or more
source-backed objects the pilot can actually report in sight. It is separate
so schema-v1 procedure files remain byte-contract compatible with older game
builds, which never request the new manifest.

The top level is:

```json
{
  "schema_version": 1,
  "airport": "KLGA",
  "variants": []
}
```

Each variant entry names an existing `procedure_id` and `variant_id`, declares
one `default_reference_id`, and contains one to eight references. Every
reference has a stable uppercase `id`, canonical spoken `name`, zero to sixteen
case-insensitively unique `aliases`, one geometry object, and its own current
authoritative `source`. The default must name exactly one entry in the same
reference array.

Supported static geometry is deliberately narrow:

- `{"kind": "point", "leg_id": "GACAR"}` uses exactly one existing leg,
  while a point independent of the route uses one finite latitude/longitude
  pair.
- `{"kind": "route", "leg_ids": [...]}` uses at least two existing legs in
  their original source order, while an independent visible route uses two to
  sixty-four coordinate points.
- `{"kind": "airport"}` uses the session airport reference point.
- `{"kind": "runway"}` uses the exact threshold of that variant's runway.

An object passes review only when the current official chart, AIP, or applicable
ATC rule supports reporting that object for that procedure. A route-leg label,
fix name, nearby landmark, or plausible map feature is not evidence. Preceding
traffic is dynamic and is not part of this static sidecar. If a variant has no
defensible reference, omit it from the sidecar and record the reason in the
launch portfolio; current clients will withhold that named variant while
generic visual approaches remain available.

The validator rejects an airport's entire sidecar for unknown keys, duplicate
IDs or phrases, invalid or non-finite coordinates, a missing default, a
procedure/variant mismatch, a missing leg, route legs out of source order, an
invalid source, files over 128 KiB, more than 64 variants, or any configured
array limit. Never infer a target from `sight_reference_point_id` to repair a
rejection.

## Published visual go-arounds

`visual_go_arounds.json` is an optional sibling of `visual_procedures.json`.
It exists only for charted visuals whose authoritative chart publishes a
go-around route. Keeping it separate preserves the visual schema-v1 contract:
older simulator builds never request the new manifest and continue to consume
the same approach files.

The top level is:

```json
{
  "schema_version": 1,
  "airport": "KSFO",
  "go_arounds": []
}
```

Each entry is keyed by an existing `procedure_id` and `variant_id`, repeats the
exact runway, carries its own authoritative `source`, declares a
`terminal_policy`, and contains ordered normalized missed legs. The validator
requires the key and runway to match the sibling visual procedure. Do not add
a sidecar entry to give an ordinary visual a convenient escape route: absence
is meaningful and makes the controller assign heading or altitude in the game.

Legs use stable `sequence`, `ident`, and ARINC `path_term` fields plus only the
geometry and constraints that the chart publishes. Supported terms are `AF`,
`CA`, `CD`, `CF`, `CI`, `CR`, `DF`, `FA`, `FC`, `FD`, `HF`, `HM`, `RF`, `TF`,
`VA`, `VD`, `VI`, `VM`, `FM`, and `VR`. Coordinate-less course, altitude,
intercept, and manual terminators remain genuine legs; never fabricate a fix
to make them look like `TF`. Altitudes use `altitude1`, optional `altitude2`,
and `altitude_desc`: `@` exact, `+` at-or-above, `-` at-or-below, or `B` for a
low-to-high window. `speed_limit` is a published maximum.

`sequence`, `altitude1`, `altitude2`, and `speed_limit` are JSON integers; the
validator never rounds fractional values. Latitude and longitude fields are
always supplied as a pair and validated independently. A real zero coordinate
is valid—the presence of the two keys, not a zero-value sentinel, determines
whether a leg has coordinates.

The final term determines the terminal policy. `HM` requires
`HOLD_INDEFINITE`, `HF` requires `HOLD_ONCE`, and every other final term uses
`REQUEST_INSTRUCTIONS`. Never synthesize a hold when the chart ends on a
course or manual terminator.

## Sources and licensing

Transcribe operational facts only: fixes or landmarks, tracks, turns, arcs,
altitude/speed restrictions, runway, and effective cycle/date. The reviewer
must be able to open the cited official chart, AIP, FAA TPP/Order, or authorised
ANSP product and compare every leg.
Do not submit a route from memory, a simulator screenshot, an unofficial map,
or a secondary page without an authoritative source behind it.

Do not commit chart PDFs, raster plates, screenshots, airport diagrams, or
copied chart artwork. Those works can be copyrighted; the JSON is a factual
transcription of operational data and remains subject to this repository's
CC BY-NC-SA 4.0 contribution licence. Keep the source URL and effective date
in the JSON so maintainers can re-check the current chart immediately before
merge.

## Checks

Follow the [visual contribution checks](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Visual-Procedures#validate) and
[local installation guide](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Test-Locally#visual-procedures-and-their-companion-files).
Keep related source files together; generated indexes are CI-owned.

## The raw-file index

`.voiceatc/visual_procedures_manifest.json`, its go-around counterpart, and
`.voiceatc/visual_sight_references_manifest.json` map each ICAO to the
repository path, canonical LF-byte SHA-256, and byte size. They are direct
raw-file indexes: none is a release archive, and none may cause a visual-
procedure ZIP to be added.

These indexes are written by CI, never by hand. `format-all-json.yml` rebuilds them after
every merge with `--preserve-published-at`, because formatting changes the
protected bytes without being a new publication, and `daily-release.yml` mints
the actual publication timestamp nightly. Each writer verifies its own output
with `--validate-only` immediately afterwards, so drift is caught where it can
be repaired rather than on a contributor's pull request.

## Maintainer review checklist

- [ ] The airport folder is registered and the payload ICAO matches it.
- [ ] The official source, effective date/AIRAC, and checked date are present.
- [ ] The chart is current, accessible, and still operational; withdrawn or
      inaccessible procedures are replaced before submission.
- [ ] Every variant has one explicit entry and one sight reference; no nearest
      entry or runway is inferred by the simulator.
- [ ] Every variant intended for current clients has a sidecar entry with one
      authored default; each spoken object is supported by a current official
      source and its geometry locates that object rather than a nearby route
      label. Unsupported variants are explicitly recorded as withheld.
- [ ] Any `forward_route` policy is supported by the official procedure and
      its route-scope sight wording is faithfully transcribed; it is not used
      to turn a feeder method into a separate clearance.
- [ ] Genuine same-runway branches remain separate variants with distinct
      entry IDs/names so controllers can select them explicitly with `via`.
- [ ] TF/CF/RF/AF geometry and turn direction are transcribed from the source.
- [ ] Every RF/AF direction produces the intended sweep, never more than 300°.
- [ ] Required constraints are distinguished from recommended values.
- [ ] No retired `availability` object or free-form source-note field is
      present; published gameplay facts belong in route geometry or explicit
      constraints.
- [ ] The runway resolves in the current playable navdata and the exact
      navdata threshold is used by the simulator preview.
- [ ] No missed-approach field is embedded in `visual_procedures.json`; any
      sourced go-around is in the additive sidecar and exactly matches its
      official chart. Unsourced visuals have no sidecar entry.
- [ ] No chart artwork, invented fixture, or `Z` approach marker is present.
- [ ] `content_hierarchy.py`, all three visual validators, and the full test
      suite pass; the generated manifests are committed with the data.
- [ ] A simulator preview confirms the requested sight report, clearance,
      named path, final capture, and threshold landing.

The review lane may combine several procedures for one airport in one pull
request. A pull request is reviewed and never auto-merged by the contribution
workflow.

The curated 0.6.2 authoring order and per-procedure evidence gate are in
[`visual-procedures-launch-portfolio.md`](visual-procedures-launch-portfolio.md).
