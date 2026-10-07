# Map display (`map_display.json`)

An airport's `map_display.json` picks what its radar map shows: the fixes, VORs and NDBs a
controller there expects on the scope, and which MAPS layers start on or off. Without one,
the game draws every waypoint in view.

## In the game

On an airport with a file, the MAPS menu's FIX row shows **CUR / ALL**. CUR (the default)
draws only the listed points, at every zoom level; ALL draws every waypoint, as before. The
VOR and NDB rows follow the same switch when the file lists them. Players can also
right-click the map to hide a drawn point or show a nearby hidden one; their choices are kept
per airport. Layer defaults apply until the player changes a MAPS layer at that airport;
from then on, their own choice wins.

## Format

The file sits in the airport folder, beside `procedure_options.json`
([placement](CONTENT_HIERARCHY.md#asset-placement)).

```json
{
  "airport": "LEBL",
  "schema": 1,
  "notes": "Optional: where the list comes from.",
  "layers": { "VOR": true, "VOR Labels": true, "Low Airways": false },
  "fixes": ["RULOS", "SLL", { "ident": "TOTKI", "lat": 41.12, "lon": 1.89 }],
  "vors": ["BCN"],
  "ndbs": []
}
```

| Key | Meaning |
|---|---|
| `airport` | ICAO code; must match the folder name. |
| `schema` | Optional; `1`. |
| `notes` | Optional free text for reviewers. |
| `layers` | Optional. MAPS layer name → `true`/`false`: `VOR`, `VOR Labels`, `NDB`, `NDB Labels`, `FIX`, `FIX Labels`, `Low Airways`, `High Airways`, `GEO` (sets its three children), `GEO Coastlines`, `GEO Lakes`, `GEO Rivers`, `RWY`, `RWY Labels`, `MRVA`, `MRVA Labels`, `MISC`, `MISC Labels`, `ILS`. Names are case-insensitive. |
| `fixes`, `vors`, `ndbs` | Optional lists. An entry is an ident (`"RULOS"`), matched to the point of that type nearest the airport, or `{"ident", "lat", "lon"}` when two points share the ident nearby. Leaving a list out keeps every point of that type; an empty list hides them all. |

A file needs `layers` or at least one list.

## Choosing the points

List what the airport's approach scope really shows: the fixes named on its STARs,
approaches and SID exits, and the navaids those procedures use. Leave out coded RNAV
points (for example `BL459`) unless a controller there refers to them. Cite the charts or
the navdata cycle in `notes`. LEBL's file is a worked example.

## Checks

```bash
python tools/map_display_manifest.py --validate-sources
python tools/content_hierarchy.py --validate-only
```

CI formats the JSON and writes `.voiceatc/map_display_manifest.json` after the merge. The
game skips an ident it cannot find, so a typo hides one point instead of breaking the
airport. To test before submitting, copy the file to the game's
`user://community/map_display/local/<ICAO>.json`.
