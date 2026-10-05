# Skins modding guide

The contributor guide now lives in the [community wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring).
Start at [Skins](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skins) for a first edit and local preview.

## Quick start

See [Quick start](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#quick-start).

Canonical example, checked by the repository skin tests:

```json
{
  "$schema": "../../tools/interface_contract/interface.schema.json",
  "name": "Harbour Blue",
  "author": "Your name",
  "extends": "generic",
  "tokens": { "colors": { "bar": "10233F", "panel": "0E1C33", "accent": "2F6DB5" } }
}
```

## The five parts

See [The five parts](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#the-five-parts).

## Extends

See [Extends](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#extends).

## Slots and parity

See [Slots and parity](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#slots-and-parity).

## Capabilities

See [Capabilities](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#capabilities).

## The validator

See [The validator](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#the-validator).

## Live reload

See [Live reload](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#live-reload).

## Cookbook

See [Cookbook](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#cookbook).

### A three-colour recolour

See [A three-colour recolour](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#a-three-colour-recolour).

Canonical example, checked by the repository skin tests:

```json
{
  "name": "Harbour Blue",
  "extends": "generic",
  "tokens": { "colors": { "bar": "10233F", "panel": "0E1C33", "accent": "2F6DB5" } }
}
```

### A minimal dark skin

See [A minimal dark skin](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#a-minimal-dark-skin).

Canonical example, checked by the repository skin tests:

```json
{
  "name": "Night Shift",
  "author": "Jane Modder",
  "extends": "generic",
  "tokens": {
    "colors": {
      "bar": "05070B", "edge": "1A1F2A", "panel": "080B11", "title": "10141C",
      "accent": "1E2A3D", "well": "05070B", "button": "10141C", "field": "05070B",
      "text": "A7B0C0", "dim": "5D6678", "value": "E4E8F0", "scope": "020305"
    },
    "case": "upper"
  },
  "primitives": {
    "window": { "title": { "height": 22 } },
    "list": { "row_height": 20, "current": { "mark": "<", "left_bar": 0 } }
  }
}
```

### The radio as a status line

See [The radio as a status line](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#the-radio-as-a-status-line).

Canonical example, checked by the repository skin tests:

```json
{
  "name": "Quiet Radio",
  "extends": "generic",
  "components": { "radio": { "mode": "status_line" } }
}
```

### A STARS-like DCB bar

See [A STARS-like DCB bar](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#a-stars-like-dcb-bar).

Canonical example, checked by the repository skin tests:

```json
{
  "name": "Square Buttons",
  "extends": "generic",
  "components": {
    "top": {
      "mode": "dcb_grid",
      "slots": {
        "columns": [
          {"ids": ["maps"]}, {"ids": ["procs"]}, {"ids": ["airspaces"]},
          {"ids": ["tag", "range"]}, {"ids": ["vector", "tl"]}, {"ids": ["com", "tfc"]},
          {"ids": ["vprof"]}, {"ids": ["warp", "pause"]}, {"ids": ["clr_qdm", "clr_routes"]},
          {"ids": ["settings"], "width": 1.5}
        ],
        "status": [["clock", "airport", "qnh"], ["rwy"], ["radio"]]
      },
      "templates": { "range": "RANGE\n{value}", "airspaces": "AIR\nSPACE" }
    },
    "bottom": { "mode": "merged_into_top" },
    "menus": { "mode": "dock_strip" }
  }
}
```

## Schema maintenance

The schema is a pinned copy (`tools/interface_contract/contract.json` names the game commit). Maintainers refresh
it with `python tools/sync_interface_contract.py --game <game checkout> --ref origin/closed-beta`, then
`python tools/skin_reference.py` to regenerate the key reference; a test fails if either copy is edited by hand.
The copies must retain the pinned game's exact bytes, including whitespace. `.prettierignore` excludes
`tools/interface_contract/`, and the formatting job runs the skin tests before committing. If a formatter
changes a copy, re-run the sync at the recorded `game_commit`; do not update its hash to accept the changed bytes.
