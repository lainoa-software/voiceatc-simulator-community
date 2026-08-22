<!--
Title this pull request [FIR/Airport] Updated/Fixed/Added…
For example: [ESSA] Updated MVAs, or [KZAU] Added KMKE
-->

## What this changes

<!-- One or two lines. Which airport or terminal area, and what is different. -->

## Source

<!--
Where the data comes from: chart, Chart Supplement, AIP, letter of agreement,
facility SOP, or published noise procedure. A link is ideal. "From memory" or
"looks right on the map" is not enough for us to merge.
-->

## Checks

- [ ] `python tools/content_hierarchy.py --validate-only` passes
- [ ] Changed `procedure_options.json`? Ran Prettier on the changed file, then `python tools/procedure_options_manifest.py --write`, then `--validate-only`, and committed the data file plus generated manifest
- [ ] Changed `constraints.json`? Ran Prettier on the changed file, then `python tools/constraints_manifest.py --write`, then `--validate-only`, and committed the data file plus generated manifest
- [ ] New terminal area or airport? Its entry is in `documentation/content_hierarchy.json` (`--register <scope>` writes it)
- [ ] Runway identifiers are zero-padded (`08L`, not `8L`) — unpadded ones silently match no runways
- [ ] The required `validate` check is green — approval does not override a red required check
- [ ] Checked in game, if you were able to

Do not reformat unrelated JSON merely for review style. CI still normalises
ordinary JSON formatting after merge; the two manifest-tracked files above are
the exception because their final bytes must be indexed before merge.

New here? The [modding wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki)
walks through adding an airport from scratch.
