# Player-contributed routes

Player-shared origin–destination routes, published by the VoiceATC Simulator
website. They are an **overlay** on top of the generated route tables in
`ROUTES/`: the game prefers a player route for a pair when one exists and falls
back to the generated (`LainoaSoftware`) route otherwise. The generated tables
are never modified by this tree.

## Layout

```
ROUTES/player/current/{ORIGIN[0:2]}/{ORIGIN}_{DEST}.json   subscriber cycle lane
ROUTES/player/default/{ORIGIN[0:2]}/{ORIGIN}_{DEST}.json   offline fallback lane
```

Lanes are data tiers, not AIRAC cycles — files persist across cycle rollover.
One file per origin–destination pair, at most 8 route variants per file:

```json
{
  "schema_version": 2,
  "origin": "LEMH",
  "dest": "LEPA",
  "routes": [
    {
      "id": "a1b2c3d4",
      "route": "LEMH DCT MAMEB DCT LEPA",
      "created_at": "2026-08-08T12:00:00Z",
      "creation_airac": "2607"
    }
  ]
}
```

- `id` is the first 8 hex characters of the SHA-256 of the normalized route
  string. It identifies the variant everywhere: website badges, the nightly
  status artifact, and the game's route cache.
- Routes must carry `DCT` bookends (`ORIGIN DCT … DCT DEST`), uppercase
  `A–Z0-9` tokens, no runway designators, at most 1000 characters / 120 tokens.
- Player route data is anonymous. Source JSON must not contain a contributor
  name or public pseudonym. The release overlay keeps its legacy fifth `AUTHOR`
  TSV cell empty so existing game builds remain compatible.

## Single writer

The website is the only writer of this tree. The daily release and the route
regeneration pipeline **never** create, edit, or delete files under
`ROUTES/player/` — they only read it. Manual pull requests are possible but the
website flow is preferred; `python tools/player_routes_manifest.py
--validate-only` must pass.

### Schema changes ship to the website first

The single writer deploys separately from the repository that checks it, so a
`FILE_SCHEMA_VERSION` bump must be **live on the website before** the stricter
check lands here — never the other way round. Anything the site publishes in
between is written to the old shape and rejected on arrival, and because
`--validate-only` gates the daily release, that halts MVAs, runway configs,
sector data and colour profiles too, not just routes. This is the reverse of the
rule for tightening an existing rule (raise the Python first, alone): a shape
change has a window, a stricter rule does not.

The 2026-08-10 incident is the worked example — the schema went to 2 nine hours
before the site stopped writing 1, and the 87 files published in that window
took the whole nightly release down for a day.

## Nightly validation and deprecation

The daily release checks every route against the live cycle's navigation data.
Routes that no longer resolve (a waypoint or airway disappeared) are marked
`deprecated` in `.voiceatc/player_routes_status.json` and excluded from the
published overlay TSVs — the source file here is left untouched, so a route that
validates again in a later cycle returns automatically. The website shows the
per-route status so anyone signed in can fix or remove stale routes. When
navdata is unavailable the previous statuses carry forward and the release still
ships.

### Acceptance is decided against navdata, never the compacted graph

`tools/routes_connectivity_check.py` asks the same question the game asks. To
fly `FIX AIRWAY FIX`, the game calls `NavigraphManager.get_full_airway()` —
`SELECT * FROM tbl_er_enroute_airways WHERE route_identifier = ? ORDER BY seqno`,
with **no `icao_code` filter** — and `RouteDecoder._expand_airway_segment` slices
that list between the two named fixes. So the check is simply *are both fixes on
that airway*, answered from `tbl_er_enroute_airways`.

The compacted route graph must **not** be used for this. It is built for route
*generation* and deliberately collapses any node with in/out degree 1 (or 2),
which deletes most pass-through fixes; it also holds no oceanic lat/lon fixes,
and it cannot see that an airway split across FIRs by `icao_code` is one airway.
Validating against it rejected 124 of 416 correct routes in the 2026-08-09
import. `--graph-db` is now optional and backs only the FRA DCT *warning*, which
never deprecates a row.

Consequences worth remembering:

- Oceanic fixes (`59N142W`, `0330N13300E`) are matched by shape — they exist in
  no table. See `COORDINATE_FIX_RE`.
- An unresolvable token is reported once, by name, as `point_missing`. The old
  `route_token_pattern` / `token_unknown` codes stayed in `DEPRECATING_CODES` for
  previously stored statuses but are no longer emitted.
- A route is inspected to the end; one bad token no longer hides later faults.
