# Community content hierarchy

> This page is the machine-backed rule set the tools enforce, for maintainers and
> for settling arguments. If you are **adding** an airport or terminal area, the
> [modding wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki)
> teaches the same rules in order, with worked examples.

The canonical operational path is:

`Region / [Nationality area] / FIR-or-ARTCC / [ACC group] / Terminal area / [Airport]`

Bracketed layers are optional. There may be at most one ACC group. The machine-readable authority is [`content_hierarchy.json`](content_hierarchy.json); paths and examples must agree with it.

## Examples

- Continental United States: `K/KZHU/AUSTIN_TMA/KAUS`
- Germany: `E/ED/EDGG/EDDF_TMA/EDDF`
- Spain with an ACC group: `L/LE/LECM/LECM_R2/MADRID_TMA/LEMD`

The nationality layer is useful for shared country styling but is omitted when it would only duplicate the region. In particular, continental U.S. paths start with `K/<ARTCC>` and never use `K/K?/KXXX`.

## Release compatibility aliases

The canonical U.S. colour and style profile is stored once at `K/colors.json` and `K/style.json`. Release packages project it to `K/KA` through `K/KZ` so simulator versions that predate region-level profiles can load the same data. The public colour manifest therefore omits the depth-one `K` scope and lists the 26 depth-two aliases instead.

These paths are distribution adapters, not geographic or contributor-facing folders. Do not create `K/KA`–`K/KZ` colour or style files in the source tree. The hierarchy registry declares the complete alias set, release packaging copies bytes from the canonical `K` files, and validation rejects source aliases. Compatibility is retained until an explicit, separately reviewed deprecation.

Community publication does not require a simulator-channel promotion once the generated manifest/archive pass the legacy-build acceptance checks. The aliases must remain present until a separate compatibility deprecation establishes a newer minimum supported simulator version.

## Identifier rules

- The operational layer must be a registered, real FIR or ARTCC/control-area identifier from the hierarchy registry.
- Region and nationality both come from the FIR code, so the nationality area always starts with its region letter: `LFFF` is filed at `L/LF/LFFF`, never `E/LF/LFFF`. Registering an area under any other region is rejected — a folder filed by continent rather than by code put France, Greece, Italy, Austria, Portugal and Switzerland under `E` for a month before this check existed.
- `XX` and `XXX` placeholders such as `EDXX`, `KXXX`, or similar nationality placeholders are not operational areas and are prohibited.
- Outside the United States, the registry uses the declared Navigraph AIRAC authority set. U.S. assignments use the declared FAA NASR authority set.
- Update the registry authority metadata and re-audit assignments when the baseline cycle changes.

## Asset placement

| Asset | Scope |
|---|---|
| `runway_configs.json` | Airport folder |
| `constraints.json` | Airport folder |
| `procedure_options.json` | Airport folder |
| `visual_procedures.json` | Airport folder |
| `visual_go_arounds.json`, `visual_sight_references.json` | Airport folder beside `visual_procedures.json` |
| `mva.json` | Terminal-area folder |
| `misc_drawings.json` | Terminal-area folder |
| `sector_configs.json`, `sector_definitions.json`, `sector_influence.json` | Terminal-area folder as one bundle |
| `colors.json`, `style.json` | Region, nationality, FIR/ARTCC, ACC, or terminal folder |

Terminal-area data can reference several airports, but each referenced airport must be registered in that terminal scope. Do not place terminal data inside an airport folder.

## Registering a new terminal area or airport

A new terminal-area folder, or a new airport inside one, needs an entry in
[`content_hierarchy.json`](content_hierarchy.json) in the same pull request. The
entry records which FIR or ARTCC the airport belongs to, sourced to the registry's
declared authority, so it is reviewed rather than inferred:

```json
"K/KZAU/MKE_TMA": ["KMKE"]
```

The validator writes it for you from the folders already on disk:

```text
python tools/content_hierarchy.py --register K/KZAU/MKE_TMA
```

## Contributor checks

Run these before opening a pull request:

```text
python tools/content_hierarchy.py --validate-only
python -m unittest discover -s tests -p "test_*.py"
```

The hierarchy validator rejects unknown operational areas, placeholders, excess ACC depth, misplaced airport or terminal files, airports assigned to the wrong registered scope, nationality areas registered under a region their own code does not start with, and release-only aliases committed as source content.

JSON formatting is **not** something to check by hand. CI normalises every JSON
file after merge, so do not run prettier yourself and do not treat indentation or
a missing trailing newline as a review finding.

`tools/generate_us_runway_configs.py` is maintainer tooling, not a contributor
check. It reproduces a one-shot import of FAA preferential-use configurations, and
several shipped airports have deliberately been improved past it — see
[`US_RUNWAY_CONFIG_SOURCES.md`](US_RUNWAY_CONFIG_SOURCES.md).
