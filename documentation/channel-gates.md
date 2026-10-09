# Channel gates: shipping new content to one game channel first

Every game build reads the same community feed, whatever its Steam channel. Stable
(0.6.1.24) and open beta (0.6.2.204) are strict: a file kind they do not know, or a zip
entry their manifest does not list, fails the whole dataset for those players. Gates let
new content reach the builds that can use it, and only those.

## The rule: content declares, builds declare

Content declares what it needs (`requires`); builds declare what they can do (their
capabilities). No version number appears in a gate, a manifest or a rule, so nothing has to
be tracked or bumped when a build ships. New contracts carry no version keys at all: a file is
identified by its path, readers ignore keys they do not know, and new meaning arrives as new
optional keys gated with `requires`.

`.voiceatc/gates.json` (edited by maintainers, never by CI):

```json
{
  "gates": [
    { "dataset": "routes", "path": "ROUTES/full/starless_arrivals.tsv", "requires": ["routes.starless_arrivals"] }
  ]
}
```

The validator reads only `gates` and ignores any other top-level key.

A gate names a `dataset` and exactly one selector:

| Selector | Matches | Example |
|---|---|---|
| `kind` | a file kind inside an entry (`colors`, `style`, …) | `{"dataset": "color_profiles", "kind": "style", …}` |
| `path` | a repo path; `*` matches anything, including `/` | `{"dataset": "mva", "path": "E/ED/EDDM/*", …}` |
| `path` (routes) | a route overlay under `ROUTES/full/`; needs `requires` | `{"dataset": "routes", "path": "ROUTES/full/starless_arrivals.tsv", …}` |
| `lane` | a route lane served by the API worker | `{"dataset": "routes", "lane": "next", …}` |

and at least one rule:

- `requires`: a non-empty list of capability names the game build must have to use the content
  (see the registry below). Names are lowercase and dotted, matching
  `[a-z0-9_]+(\.[a-z0-9_]+)+`, at most 64 characters, no duplicates. When several gates match
  one file or entry, their `requires` lists are merged.
- `channels`: the Steam channels allowed (`stable`, `open-beta`, `closed-beta`). Leave it out
  to allow every channel.

Gateable datasets: `mva`, `runway_configs`, `sector_data`, `misc_drawings`,
`color_profiles` (kind and path gates); `routes` (path gates on overlays under `ROUTES/full/`,
always with `requires`; see "Route overlays" below); `routes`,
`voice_priors`, `snapshots` (lane gates, read by the API worker, never by this release).

There is no `min_game_version` and no per-channel version list. Old gate files that use
`min_game_version` are rejected by the validator.

## Capability registry

A capability is a named thing a build can do. Builds that read the full feed report the names they
support; the table says which game build line first supports each name, for maintainers
only. The release never reads that column.

| Capability | Meaning | First supported by |
|---|---|---|
| `community.full_feed` | Reads the full manifests under `.voiceatc/full/` and filters entries by `requires` and `channels`. | closed beta (0.6.2 line) |
| `routes.starless_arrivals` | Flies an arrival filed to an approach transition's first fix (no STAR) and reads `.voiceatc/full/routes_manifest.json`. | closed beta (0.6.2 line) |
| `routes.route_rules` | Reads the contributor route rules overlay `ROUTES/full/route_rules.tsv` (rows rebuilt from `ROUTES/rules/`). Its gate is `closed-beta` only and comes after the starless gate, so the starless-only variant stays open to every channel. | closed beta (0.6.3 line) |

To add a capability, add a row here in the same pull request that adds the gate or the game
code that uses it. Names are permanent: never rename one, add a new name instead.

## What the daily release does with them

For each zip dataset the release writes two outputs:

1. **Default** (`.voiceatc/<dataset>_manifest.json` and `<asset>.zip`): exactly today's
   format. An entry stays when it has no gate, or when its gate has no `requires` and its
   `channels` is absent or lists all three channels. Old builds know no capabilities, so
   anything that requires one stays out. A gated file that does not stay is left out of the
   manifest and the zip.
   When that removes a required file (a profile's `colors`, any sector-data file), the whole
   entry is left out. With no gates, the default output is byte-identical to before.
2. **Full** (`.voiceatc/full/<dataset>_manifest.json` and `<asset>-full.zip`): everything, with
   the gate fields copied onto the gated entry (path gates on single-file entries) or file
   (`files.<kind>`). There is no version key: the path and the `dataset` key identify the
   manifest, and `entries` is a list; each entry has an `id`
   (the airport, bundle or scope key) plus today's entry fields. `requires` and `channels` stay on
   entries and files exactly as written in the gate. Game builds that read the full feed keep an entry
   or file when they have every capability in `requires` and `channels` is absent or contains
   their channel, and ignore keys they do not know. Old builds never read full-feed paths.

### Route overlays

Routes are not a zip dataset. A gated route overlay (`ROUTES/full/<id>.tsv`) holds whole
replacement rows for pairs already in `ROUTES/routes.tsv`, with the same header and columns.
`tools/routes_full_feed.py` checks every overlay (its `airac` equals `routes.tsv`, the column
line matches, every pair exists in the base, no duplicate pair, no pair in two overlays, and
a `routes` path gate with `requires`) and the release builds cumulative variants, most capable
first: variant k is the base table with overlays 1..k spliced in (gates.json order), and its
`requires` is the union of their capabilities. Each variant is a rich TSV asset
(`routes-rich-<airac>-full.tsv` for the first, `routes-rich-<airac>-full-<id>.tsv` for the rest)
listed in `.voiceatc/full/routes_manifest.json`:

```json
{
  "dataset": "routes", "repo": "…", "release_tag": "…", "commit_sha": "…",
  "published_at": "…", "generated_at": "…", "entry_count": 1,
  "entries": [{
    "id": "starless_arrivals", "airac": "2609", "source_airac": "2609",
    "asset_name": "routes-rich-2609-full.tsv", "download_url": "https://github.com/…",
    "sha256": "…", "size_bytes": 12182449, "route_count": 99856,
    "projection_id": "rich_route_coordinates_v1",
    "overlays": ["ROUTES/full/starless_arrivals.tsv"],
    "requires": ["routes.starless_arrivals"]
  }]
}
```

A build keeps the first entry whose gate it passes and whose `airac` equals its target cycle;
otherwise it reads the default routes manifest. The default tables, manifests, release manifest
and R2 mirror never change because of an overlay. At release time an overlay for another cycle
is left out with a notice, in the release and in pull requests (`routes_full_feed.py --allow-stale`).
An AIRAC rollover changes `routes.tsv` in one pull request and the overlays only later, so a
strict check would block the automated cycle pull request (creator decision, 2026-10-09).
Without `--allow-stale` the tool stays strict, for a local check.

Before anything is published, `tools/stable_contract_guard.py` replays the stable 0.6.1.24
parser rules on every default manifest and zip (schema 2, exact top-level and entry keys,
known file kinds only, every zip entry listed and hash-matched, counts equal) and the open
beta exact-key rule on the visual manifests. It also fails when any default manifest or the
release manifest asset names `ROUTES/full/` or a `-full` routes asset. A failure stops the release.

## Frozen legacy labels

The default feed keeps the version labels shipped builds already check, because stable
0.6.1.24 and open beta 0.6.2.204 reject a manifest whose `schema_version` differs. They are
frozen in one place, `tools/legacy_contract.py` (the `LEGACY_*` constants), and never change:

| Default-feed file | `schema_version` |
|---|---|
| `.voiceatc/{mva,runway_configs,sector_data,misc_drawings,color_profiles}_manifest.json` | 2 |
| `.voiceatc/release_manifest.json` | 4 |
| `.voiceatc/routes_manifest.json` | 2 |
| routes release manifest asset, `ROUTES/routes_default_manifest.json` | 1 |
| `.voiceatc/constraints_manifest.json`, `.voiceatc/procedure_options_manifest.json` | 1 |
| `.voiceatc/player_routes_manifest.json`, `.voiceatc/player_routes_status.json` | 1 |
| `.voiceatc/visual_{procedures,go_arounds,sight_references}_manifest.json` and their files | 1 |

`tools/stable_contract_guard.py` checks these values independently. The rule for everything
new (`gates.json`, the full feed, any future dataset): no version keys;
gate new content with `requires`.

## Recipes

- **New content for closed beta only:** add a gate with `"channels": ["closed-beta"]`, and a
  `requires` entry when older closed-beta builds cannot read it.
- **Promote to open beta:** add `open-beta` to `channels`.
- **New file kind or field:** pick a capability name, add a registry row, and gate the kind
  with `"requires": ["<name>"]`. Builds that have the capability read it from the full feed; the default
  feed never carries it.
- **Overlay (different routes for capable builds):** put the replacement rows in
  `ROUTES/full/<id>.tsv` (same header and `airac` as `routes.tsv`), add a registry row and
  `{"dataset": "routes", "path": "ROUTES/full/<id>.tsv", "requires": ["<name>"]}`, and run
  `python tools/routes_full_feed.py --validate-only`. Regenerate the overlay with each new
  cycle of `routes.tsv`; a stale one is left out of the release.
- **Everyone can read it:** content that requires a capability stays out of the default feed
  for good, because old builds cannot know the capability. To serve it to everyone, ship the
  old-build-safe form of the data in the default format and drop the gate.

Check your edit locally:

```
python tools/release_gates.py --validate-only
python tools/routes_full_feed.py --validate-only
python -m unittest discover -s tests -p "test_*.py"
```

Contributors do not edit gates. If a pull request adds a new file kind or a new field, a
maintainer adds the gate in the same pull request so it never reaches stable players early.
