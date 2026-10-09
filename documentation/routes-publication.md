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

## Contributor route rules (`ROUTES/rules/`)

Rules from the website's closed-beta tester lane, one file per rule:
`ROUTES/rules/<ICAO>/<id>.json`. They do not edit any route table and nothing
in the daily release reads them. The Routes-repo compile job turns accepted
rules into builder facts and publishes the rebuilt routes as a route overlay
gated to the `closed-beta` channel. `tools/route_rules_check.py` validates the
shape in every pull request and release. Contract:
[`ROUTES/rules/README.md`](../ROUTES/rules/README.md).

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

## Gated overlays (`ROUTES/full/`)

Some generated routes only suit builds that have a capability. The first is
`routes.starless_arrivals`: when every STAR entry for a pair lies behind the aircraft, the
generator files the arrival to an approach transition's first fix instead, and only builds
that fly that fix as the clearance limit may receive it. Such rows never enter
`routes.tsv`; they go in an overlay, `ROUTES/full/<id>.tsv`, that holds only the replacement
rows (same header, `airac` and five columns as `routes.tsv`) and is gated in
`.voiceatc/gates.json` with `requires`.

- `python tools/routes_full_feed.py --validate-only` checks the overlays (it runs in the
  required pull-request gate and before every daily release).
- `python tools/routes_connectivity_check.py --routes-path ROUTES/full/<id>.tsv
  --navdata-db <navdata> --accept-approach-entries` checks overlay rows against navdata.
  Accepting an approach-entry arrival end is opt-in and used only for `ROUTES/full/*`: the
  default table and player routes stay on the strict STAR-entry rule, because the
  builds that read them cannot fly an approach-fix arrival end.
- The daily release splices the overlays into full-feed tables
  (`routes-rich-<airac>-full*.tsv`) listed in `.voiceatc/full/routes_manifest.json`.
  The default tables, `.voiceatc/routes_manifest.json`, `.voiceatc/release_manifest.json`
  and the R2 mirror stay byte-identical, and `tools/stable_contract_guard.py` fails a release
  whose default feed names an overlay or a full routes asset.
- An overlay belongs to one cycle. Regenerate it with each new `routes.tsv` cycle; until
  then the release leaves it out and capable builds read the default table.

Contract, variants and the manifest shape: [`channel-gates.md`](channel-gates.md#route-overlays).

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
