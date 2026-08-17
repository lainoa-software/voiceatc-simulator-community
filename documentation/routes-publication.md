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

`ROUTES/routes.tsv` and `ROUTES/routes_default_rich.tsv` are the coordinate-capable
current/default route tables. Their `routes_legacy.tsv` and `routes_default.tsv`
companions are deterministic projections for older simulator builds. Release
manifests deliberately keep the legacy asset in the existing root fields and expose
the rich asset under `rich_routes_tsv`; contributors must update both through the
route projection tool, never edit the legacy copy independently. The daily release
publishes both assets with unchanged manifest schema versions.
