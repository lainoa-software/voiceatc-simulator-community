# Route publication

How the route tables in `ROUTES/` are produced and published. This is maintainer
and website territory — contributors adding airports or sectors do not need it.

## Player-contributed routes (`ROUTES/player/`)

Player-shared origin–destination routes published by the VoiceATC Simulator
website. They overlay the generated route tables — the game prefers them per
pair and falls back to the generated route — and are validated against the live
cycle every night, with stale routes marked deprecated in
`.voiceatc/player_routes_status.json` rather than deleted. The website is the
single writer of this tree; regeneration and releases only read it. Contract
and lifecycle: [`ROUTES/player/README.md`](../ROUTES/player/README.md).

## Publication compatibility

The migration and contribution checker resolve US local FAA identifiers with a
leading `K` only when the exact four-character airport is absent and the local
identifier belongs to the United States. Reviewed same-site renames can be passed
with `--airport-aliases`; their manifest must name the validation cycle, an existing
target airport and a same-site distance at most 0.01 NM. Migration checks the target
cycle even while reading the prior-cycle table. Procedure checks use the resolved
airport, while the source row remains byte-identical. Missing airports still fail;
private exception and alias evidence never becomes a community release asset.

`ROUTES/routes.tsv` and `ROUTES/routes_default_rich.tsv` are the coordinate-capable
current/default route tables. Their `routes_legacy.tsv` and `routes_default.tsv`
companions are deterministic projections for older simulator builds. Release
manifests deliberately keep the legacy asset in the existing root fields and expose
the rich asset under `rich_routes_tsv`; contributors must update both through the
route projection tool, never edit the legacy copy independently. The daily release
publishes both assets with unchanged manifest schema versions.

## Generated-route evidence boundary

The private generator may use licensed-planner comparisons to correct its
`LainoaSoftware` base rows. Only the final accepted five-column Generated rows and
their normal projection/release artifacts belong in this repository. Capture
journals, written-authorization records, account details, source-record ids,
inferred-policy files, exception proofs, and private conformance certificates must
never be committed here or included in release assets.

This boundary does not change route precedence: a valid current-cycle player route
still overlays the Generated row, and any player-overlay failure falls back to that
Generated row. Rich and legacy tables must retain identical OD coverage and remain
deterministic projections of the same accepted route data.
