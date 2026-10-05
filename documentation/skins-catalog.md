# The skins catalog: make and submit a skin

The contributor guide now lives in the [community wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Catalog).
Start at [Skins](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skins) for a first edit and local preview.

## Make one

See [Make one](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Catalog#make-one).

Canonical example, checked by the repository skin tests:

```json
{
  "name": "Harbour Blue",
  "author": "Jane Modder",
  "description": "Cool blue bevelled cells with upper-case chrome.",
  "extends": "generic",
  "tokens": {
    "colors": { "bar": "1F3555", "edge": "35527D" },
    "fonts": { "text": "barlow_semi_condensed" },
    "case": "upper",
    "bevel": { "width": 2 }
  },
  "primitives": {
    "bar_cell": { "states": { "normal": { "box": { "kind": "bevel", "fill": "bar" } } } }
  }
}
```

## What you can and cannot change

See [What you can and cannot change](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Catalog#what-you-can-and-cannot-change).

## Preview before you submit

See [Preview before you submit](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Catalog#preview-before-you-submit).

## Submit

See [Submit](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Catalog#submit).

## How it ships (maintainers)

The catalog is published **only** in the full feed: `.voiceatc/full/skins_manifest.json` and the `skins-full.zip`
release asset, written by `tools/community_release_manifest.py` beside the other full-feed datasets. There is no default
manifest, no default zip and no entry in the release manifest, so game builds that predate skins never read it.
`tools/stable_contract_guard.py` fails the release if any of those default paths appears. `.voiceatc/gates.json`
holds a `skins` path gate that requires the `skins.catalog` capability, copied onto each full-feed entry as `requires`;
see [channel gates](https://github.com/lainoa-software/voiceatc-simulator-community/blob/main/documentation/channel-gates.md).

Each full-feed entry has the skin's `id` (the folder name), `repo_path`, `sha256`, `size_bytes`, `name`, `author` and,
when set, `description`, so the picker can list the catalog without opening the zip.
