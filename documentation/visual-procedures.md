# Charted visual procedures

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
cycle, and the date it was checked. `availability` may record published
ceiling, visibility and daylight/tower facts; those values are advisory in
simulator 0.6.2.

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

An optional `final` object may provide `course_deg` and `glidepath_deg`. Do not
write a runway threshold, missed approach, `approach_visual_segment`, contact
approach, circling route, or VFR/AFIS landing route into this schema. The game
resolves the threshold from navdata and owns go-around behavior.

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

## Sources and licensing

Transcribe operational facts only: fixes or landmarks, tracks, turns, arcs,
altitude/speed restrictions, runway, effective cycle/date, and published
availability notes. The reviewer must be able to open the cited official
chart, AIP, FAA TPP/Order, or authorised ANSP product and compare every leg.
Do not submit a route from memory, a simulator screenshot, an unofficial map,
or a secondary page without an authoritative source behind it.

Do not commit chart PDFs, raster plates, screenshots, airport diagrams, or
copied chart artwork. Those works can be copyrighted; the JSON is a factual
transcription of operational data and remains subject to this repository's
CC BY-NC-SA 4.0 contribution licence. Keep the source URL and effective date
in the JSON so maintainers can re-check the current chart immediately before
merge.

## Formatting, manifest, and checks

Normalise only the file being contributed, then generate the raw-file manifest
from the same bytes:

```text
npx prettier --write <airport>/visual_procedures.json
python tools/visual_procedures_manifest.py --write
python tools/visual_procedures_manifest.py --validate-only
python tools/content_hierarchy.py --validate-only
python -m unittest discover -s tests -p "test_*.py"
```

Commit both `visual_procedures.json` and
`.voiceatc/visual_procedures_manifest.json`. The manifest maps each ICAO to
the repository path, canonical LF-byte SHA-256, and byte size. It is a direct
raw-file index: it is not a release archive and must not cause a visual-
procedure ZIP to be added. The daily release refreshes this manifest and
commits it when its source mapping changes.

Do not hand-edit the generated manifest. If validation reports drift, rerun
`--write` after the JSON has been formatted. The checked-in manifest is
required on a review pull request so a stale or missing hash cannot reach the
nightly sync.

## Maintainer review checklist

- [ ] The airport folder is registered and the payload ICAO matches it.
- [ ] The official source, effective date/AIRAC, and checked date are present.
- [ ] The chart is current, accessible, and still operational; withdrawn or
      inaccessible procedures are replaced before submission.
- [ ] Every variant has one explicit entry and one sight reference; no nearest
      entry or runway is inferred by the simulator.
- [ ] TF/CF/RF/AF geometry and turn direction are transcribed from the source.
- [ ] Every RF/AF direction produces the intended sweep, never more than 300°.
- [ ] Required constraints are distinguished from recommended values.
- [ ] The runway resolves in the current playable navdata and the exact
      navdata threshold is used by the simulator preview.
- [ ] No missed-approach field, chart artwork, invented fixture, or `Z`
      approach marker is present.
- [ ] `content_hierarchy.py`, the visual validator, and the full test suite
      pass; the generated manifest is committed with the data.
- [ ] A simulator preview confirms the requested sight report, clearance,
      named path, final capture, and threshold landing.

The review lane may combine several procedures for one airport in one pull
request. A pull request is reviewed and never auto-merged by the contribution
workflow.

The curated 0.6.2 authoring order and per-procedure evidence gate are in
[`visual-procedures-launch-portfolio.md`](visual-procedures-launch-portfolio.md).
