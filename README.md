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
3. Open a pull request named `[FIR/Airport] Updated/Fixed/Added…`, for example
   `[ESSA] Updated MVAs`.
4. Say where the data comes from. Automatic checks run first, then a maintainer
   reviews the data itself.

`procedure_options.json`, `constraints.json`, and `visual_procedures.json` are
indexed by byte hash. Prepare either file in this order: normalize the changed JSON with
`npx prettier --write <path>`, run the matching manifest tool with `--write`, run
that tool again with `--validate-only`, then commit both the data file and the
generated `.voiceatc/*_manifest.json`. For example:

```text
npx prettier --write E/ES/ESAA/ESOS_Y/ESOS_APP/ESSA/procedure_options.json
python tools/procedure_options_manifest.py --write
python tools/procedure_options_manifest.py --validate-only
```

Use `tools/constraints_manifest.py` for `constraints.json`. Do not reformat
unrelated JSON just to satisfy review style; ordinary formatting is still
normalised automatically after merge.

For a named charted visual approach, use
`tools/visual_procedures_manifest.py` and read the full source, licensing,
schema, and review checklist in
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
