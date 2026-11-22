# Frozen legacy sector snapshots

Verbatim `sector_configs.json` (136), `sector_influence.json` (136), `sector_definitions.json`
(136), schema-1 `tma.json` (20), `mva.json` (91), `misc_drawings.json` (36),
`procedure_options.json` (61), and `map_display.json` (2) bytes captured from `main`
(`dc9ce5c`) for every source that shipped before the schema-2 layout conversion.

`index.json` records, per bundle under `bundles`, the SHA-256 hashes of its schema-2
source files (`tma_structure.json`, `tma_coordination.json`, `sector_definitions.json`,
and the nearest ancestor `acc_structure.json`) as converted by commit 0002, plus any
unit/sector ID aliases and metadata needed when regenerating edited bundles. Under
`files`, it records the schema-2 source hash for each `mva.json`, `misc_drawings.json`,
`procedure_options.json`, and `map_display.json`.

At publish time, `tools/sector_legacy_projection.py` compares each bundle's or file's
current schema-2 source hashes against `index.json`: unchanged sources ship these
frozen bytes verbatim, while edited or new sources fall back to generating legacy
files from schema 2.
