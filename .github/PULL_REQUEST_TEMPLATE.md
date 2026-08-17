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
- [ ] New terminal area or airport? Its entry is in `documentation/content_hierarchy.json` (`--register <scope>` writes it)
- [ ] Runway identifiers are zero-padded (`08L`, not `8L`) — unpadded ones silently match no runways
- [ ] Checked in game, if you were able to

You do **not** need to run prettier or fix JSON indentation. CI formats every JSON
file after merge.

New here? The [modding wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki)
walks through adding an airport from scratch.
