# VoiceATC Simulator Community
The Github to manage custom airports and sectors for VoiceATC Simulator.

## Contributing
To contribute, fork this repository, commit your changes there and then create a pull request onto the main repository. Read [the content hierarchy guide](documentation/CONTENT_HIERARCHY.md) and the wiki pages before creating or modifying an airport.

Community assets follow `Region / [Nationality] / FIR-or-ARTCC / [ACC] / Terminal / [Airport]`. Bracketed layers are optional. The continental United States omits nationality, so Austin is `K/KZHU/AUSTIN_TMA/KAUS`, while Frankfurt is `E/ED/EDGG/EDDF_TMA/EDDF`. Placeholder identifiers such as `KXXX` and `EDXX` are prohibited. U.S. `K/KA`–`K/KZ` colour/style paths are generated release compatibility aliases only and must never be added to the source tree. Run `python tools/content_hierarchy.py --validate-only` before opening a pull request.

## Route publication compatibility

`ROUTES/routes.tsv` and `ROUTES/routes_default_rich.tsv` are the coordinate-capable
current/default route tables. Their `routes_legacy.tsv` and `routes_default.tsv`
companions are deterministic projections for older simulator builds. Release
manifests deliberately keep the legacy asset in the existing root fields and expose
the rich asset under `rich_routes_tsv`; contributors must update both through the
route projection tool, never edit the legacy copy independently. The daily release
publishes both assets with unchanged manifest schema versions.

## Objective symbol heights (`style.json`)

Vector entries under `defined_symbols` may declare a positive numeric `height` in
callsign-row units. `1.0` is exactly the rendered height of the callsign row, and
the renderer fits the symbol's complete outer height to that target without optical
normalisation. Omit `height` to retain the legacy `symbol_size` / `traildot_size`
and optical-normalisation behaviour. Keep those legacy top-level values when adding
an objective height: older simulator builds ignore the new definition field and
continue to render the compatible fallback.

## Pull Requests
In order to keep the reposititory organized, name all pull requests `[FIR/Airport] Updated/Fixed/Added...` - for example `[ESSA] Updated MVAs`. There are automatic checks that will be preformed when you create a pull request, and after those the files will be inspected by a maintainer before being merged. If any errors are spotted, we will ask you to update the pull request before we can merge it.

## Procedure options (`procedure_options.json`)
An optional per-airport file that records attributes for each of the airport's procedures. Place it in the airport's folder next to `constraints.json` (e.g. `R/RC/RCAA/TAIPEI_TMA/RCTP/procedure_options.json`).

Today it controls **which procedures the automatically generated traffic may be assigned**. It does **not** change what the controller can assign manually. Behaviour is opt-out: an airport with no file, and any procedure not listed, is treated as enabled — so adding the file never reduces traffic unless you explicitly disable something.

Keys are procedure idents as they appear in the navigation data (the same idents you see in-game), grouped into `stars`, `sids`, and `iaps`. Each procedure maps to an object so more attributes can be added without changing the distribution format.

```json
{
  "airport": "RCTP",
  "schema_version": 1,
  "airac_min": 2604,
  "defaults": { "spawn_enabled": true },
  "stars": {
    "GRAC1A": { "spawn_enabled": true },
    "TONG1B": { "spawn_enabled": false }
  },
  "sids": {},
  "iaps": {}
}
```

- `spawn_enabled: false` withholds a procedure from generated traffic. Resolution order per procedure: a matching per-runway override (see below), then its own global `spawn_enabled`, then `defaults.spawn_enabled`, then `true`.
- `defaults.spawn_enabled: false` flips the airport to allow-list style (disable everything, then enable only the listed procedures).
- `init_climb` sets a generated departure's initial cleared altitude in feet. It must be a positive integer and may appear in `defaults` or a SID entry. Resolution is active-configuration SID → active-runway SID → global SID → `defaults.init_climb` → no curated override. Unlike `spawn_enabled`, this operational metadata remains active when a player customises the procedure spawn whitelist.
- A SID entry may also contain ordered `climb_variants` when a published procedure has named, mutually exclusive runway climbs that are not distinguished by the navigation-data SID ident. Each variant supplies a stable `id`, player-facing `display_name`, eligible `runways`, one `auto_rule`, and a complete replacement `legs` sequence. The first matching rule wins, and exactly one final `fallback` is required.
- `airport` must match the folder name. Run `python tools/procedure_options_manifest.py --validate-only` before opening a PR; the manifest is regenerated automatically on release.

### SID climb variants (`climb_variants`)

Climb variants are additive schema-1 data: simulator versions that do not understand them ignore the new attribute and continue using the AIRAC SID. Supported automatic rules are `route_contains` (exact filed-route token), `aircraft_type`, a half-open `utc_window` in minutes after midnight, and the required final `fallback`. Array order is policy priority.

Legs use typed procedure fields. Supported path terms are `IF`, `TF`, `DF`, `CF`, `CA`, `VA`, `VM`, and `FM`; headings use `course`, turns use `turn_direction`, and altitude/speed restrictions use the normal ARINC-style description and numeric fields. `endpoint` can define a `radial_dme` point. A `crossing.first_of` block represents the first reached DME or radial condition. Optional `containment` assertions document an `east_of_radial` or `max_dme` limit for construction and regression checks.

```json
{
  "sids": {
    "JFK5": {
      "init_climb": 5000,
      "climb_variants": [
        {
          "id": "GATEWAY",
          "display_name": "GATEWAY",
          "runways": ["31L", "31R"],
          "auto_rule": {"kind": "utc_window", "start_minute": 180, "end_minute": 720},
          "legs": [
            {"path_term": "CF", "course": 232, "endpoint": {"kind": "radial_dme", "navaid": "JFK", "radial": 232, "distance_nm": 5}},
            {"path_term": "VM", "course": 219, "turn_direction": "L"}
          ]
        },
        {
          "id": "CANARSIE",
          "display_name": "CANARSIE",
          "runways": ["31L", "31R"],
          "auto_rule": {"kind": "fallback"},
          "legs": [{"path_term": "FM", "course": 176}]
        }
      ]
    }
  }
}
```

### Per-runway overrides (`runways`)
Most procedures are already locked to one landing/departure direction by the navigation data, so the per-procedure flags above are usually enough. When a **shared** procedure (one that serves more than one direction) should be available for one runway but not another, add an optional top-level `runways` object. Each key is a bare runway token (e.g. `"25"`); its `stars`/`sids`/`iaps` use the same per-procedure shape and override the global flag **only** when that runway is active.

```json
{
  "airport": "EDDS",
  "schema_version": 1,
  "airac_min": 2604,
  "defaults": { "spawn_enabled": true },
  "stars": {
    "REUT5A": { "spawn_enabled": false }
  },
  "runways": {
    "25": { "stars": { "GEBN1W": { "spawn_enabled": true } } },
    "07": { "stars": { "GEBN1W": { "spawn_enabled": false } } }
  }
}
```

### Approach transitions / feeders (`transitions`)
Approaches often have feeder **transitions** (an IAF feeder such as `LBU25`) that bridge enroute traffic onto the final approach. At airports whose arrivals already lead onto the final approach, those feeders are rarely flown, and you may not want auto-generated traffic spawning onto them. Add an optional `transitions` block to forbid them for generated traffic. It only affects spawned traffic — a controller can still clear any feeder manually.

The block mirrors the per-procedure shape but also accepts a blanket `spawn_enabled` directly under `transitions` (like `defaults`): set it once to disable **every** feeder, and optionally re-enable named feeders. The **final approach itself is never affected** — aircraft are simply vectored onto final instead of flying the feeder. You can also nest `transitions` inside a `runways` entry for per-direction control.

```json
{
  "airport": "EDDS",
  "schema_version": 1,
  "airac_min": 2604,
  "transitions": { "spawn_enabled": false }
}
```

Granular form (forbid all feeders except one), and the per-feeder resolution order — per-runway per-feeder → global per-feeder → per-runway blanket → global blanket → `defaults.spawn_enabled` → enabled:

```json
{
  "airport": "EDDS",
  "schema_version": 1,
  "transitions": {
    "spawn_enabled": false,
    "LBU25": { "spawn_enabled": true }
  }
}
```

Keys are matched case-insensitively, so you may write idents (and the rest of the file) in lower case if you prefer consistent formatting.

## Minimum vectoring altitudes (`mva.json`)
An optional file at the terminal-scope folder (e.g. `K/KZNY/JFK_TMA/mva.json`) that gives the simulator minimum vectoring altitude areas for low-altitude alerts and the MRVA map display. `airport` names the served airport (an `airports` array may share one file across a terminal group). `mva_areas` rows carry `area_id`, `minimum_altitude_ft` (positive integer), a closed `[lat, lon]` `polygon` ring, and optional `labels` (`text`, `position`) for the altitude readout on scope.

For U.S. airports the authoritative source is the FAA's AIXM 5.1 MVA publication (<https://aeronav.faa.gov/MVA_Charts/aixm/>, one `<FACILITY>_MVA_FUS*.xml` per TRACON/ATCT). Use the **FUS3** variant of a facility's chart — the same choice the Vice ATC simulator makes for its bundled MVA data. Conversion conventions: keep the sectors relevant to the playable terminal area, drop AIXM interior rings only when each hole is covered by a higher-MVA lettered sector (the simulator evaluates the highest MVA of all polygons covering a point, so the hole region still resolves correctly; verified for N90 FUS3), and emit one label per area with the altitude in full feet.

Run `python tools/mva_manifest.py --validate-only` before opening a PR; the manifest is regenerated automatically on release.

## Bugs, Suggestions & Feedback
Open Github issues regarding the issue, suggestion or feedback. Remember to explain it thoroughly so someone can help you.

## Discord
If you have more questions, send a message in the questions-channel in our Discord. https://discord.gg/Hr4Z8e3cyn

## License
[![CC BY-NC-SA 4.0][cc-by-nc-sa-shield]][cc-by-nc-sa]

This repository is licensed under a
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License][cc-by-nc-sa].

[![CC BY-NC-SA 4.0][cc-by-nc-sa-image]][cc-by-nc-sa]

[cc-by-nc-sa]: http://creativecommons.org/licenses/by-nc-sa/4.0/
[cc-by-nc-sa-image]: https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png
[cc-by-nc-sa-shield]: https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg
