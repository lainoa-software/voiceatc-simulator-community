# VoiceATC Simulator Community

Custom airports, terminal areas, and sectors for VoiceATC Simulator. Everything
here is community-contributed data, published to the game nightly.

## Start here

**[The modding wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki)
is the manual.** It walks through adding an airport from an empty folder to a
merged pull request, one file type at a time.

| I want to | Go to |
|---|---|
| Add or fix an airport | [Airport](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Airport) → [Runway Configs](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Runway-Configs) |
| Set which procedures spawn | [Procedure Options](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Procedure-Options) |
| Add a charted visual approach | [Charted visual procedures](documentation/visual-procedures.md) |
| Draw MVAs or radar geometry | [MVA](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/MVA), [Sector Definitions](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Sector-Definitions) |
| Match a radar display | [Colours](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Colours), [Styles](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Styles) |
| Check my work and submit it | [Validate and Submit](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Validate-and-Submit) |

## Where your files go

```text
Region / [Nationality] / FIR-or-ARTCC / [ACC] / Terminal / [Airport]
```

Bracketed layers are optional. Austin is `K/KZHU/AUSTIN_TMA/KAUS` — the
continental United States omits the nationality layer. Frankfurt is
`E/ED/EDGG/EDDF_TMA/EDDF`.

A new terminal area or airport also needs one line in
[`documentation/content_hierarchy.json`](documentation/content_hierarchy.json).
Do not write it by hand — create the folders, then run:

```text
python tools/content_hierarchy.py --register K/KZAU/MKE_TMA
```

Full rules, including the prohibited `KXXX`/`EDXX` placeholders and the
generated `K/KA`–`K/KZ` release aliases that must never be added to the source
tree: [the content hierarchy guide](documentation/CONTENT_HIERARCHY.md).

## Contributing

1. Fork this repository and commit your change on a branch.
2. Run `python tools/content_hierarchy.py --validate-only`, plus the validator
   for the file you edited — see
   [Validate and Submit](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Validate-and-Submit).
3. Test it in your own game first — see
   [Validate and Submit](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Validate-and-Submit)
   § Test in the game.
4. Open a pull request named `[FIR/Airport] Updated/Fixed/Added…`, for example
   `[ESSA] Updated MVAs`.
5. Say where the data comes from. Automatic checks run first, then a maintainer
   reviews the data itself.

`procedure_options.json`, `constraints.json`, `visual_procedures.json`,
`visual_go_arounds.json`, and `visual_sight_references.json` are also listed in
an index under `.voiceatc/` that records each file's byte hash and size, so the
game can verify what it downloads. You do not maintain that index. CI rebuilds
it after your pull request merges and again in the nightly release, and a pull
request that leaves it out of date is still correct and still merges.

Validate only the file you contributed:

```text
python tools/procedure_options_manifest.py --validate-sources
```

Use `tools/constraints_manifest.py` for `constraints.json`. Do not run Prettier
and do not commit anything under `.voiceatc/`; ordinary formatting is normalised
automatically after merge.

For a named charted visual approach, use
`tools/visual_procedures_manifest.py` and, when publishing its reportable sight
objects, `tools/visual_sight_references_manifest.py`. Read the full source,
licensing, schema, and review checklist in
[`documentation/visual-procedures.md`](documentation/visual-procedures.md).
The visual manifest is a direct JSON index; it does not create a release ZIP.

A maintainer approval does not override a red required `validate` check. Both
approval and a green required check are necessary before merge.

## Reference

- [Content hierarchy](documentation/CONTENT_HIERARCHY.md) — folder rules the
  tools enforce.
- [US runway config sources](documentation/US_RUNWAY_CONFIG_SOURCES.md) — where
  the shipped US preferential configurations came from.
- [Route publication](documentation/routes-publication.md) — how the `ROUTES/`
  tables are produced. Maintainer and website territory.

## Bugs, suggestions and feedback

Open a GitHub issue and explain it thoroughly enough that someone can help.

## Discord

For anything else, ask in the questions channel: https://discord.gg/Hr4Z8e3cyn

## License

[![CC BY-NC-SA 4.0][cc-by-nc-sa-shield]][cc-by-nc-sa]

This repository is licensed under a
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License][cc-by-nc-sa].

[![CC BY-NC-SA 4.0][cc-by-nc-sa-image]][cc-by-nc-sa]

[cc-by-nc-sa]: http://creativecommons.org/licenses/by-nc-sa/4.0/
[cc-by-nc-sa-image]: https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png
[cc-by-nc-sa-shield]: https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg
