# Session skins: `panels.json`

The contributor guide now lives in the [community wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Regional-Skins).
Start at [Skins](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skins) for a first edit and local preview.

## A skin changes the look, never the features

See [A skin changes the look, never the features](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Regional-Skins#a-skin-changes-the-look-never-the-features).

## Where it goes

See [Where it goes](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Regional-Skins#where-it-goes).

## Minimal example

See [Minimal example](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Regional-Skins#minimal-example).

Canonical example, checked by the repository skin tests:

```json
{
  "extends": "generic",
  "tokens": { "case": "upper", "bevel": { "width": 2 } },
  "primitives": {
    "bar_cell": { "states": { "normal": { "box": { "kind": "bevel", "fill": "bar" } } } }
  }
}
```

## Name, author and description

See [Name, author and description](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Regional-Skins#name-author-and-description).

## Checks and shipping

See [Checks and shipping](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Regional-Skins#checks-and-shipping).
