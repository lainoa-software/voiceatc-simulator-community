# Skins modding guide

The contributor guide now lives in the [community wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring).
Start at [Skins](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skins) for a first edit and local preview.

## Quick start

See [Quick start](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#quick-start).

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

### A minimal dark skin

See [A minimal dark skin](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#a-minimal-dark-skin).

### The radio as a status line

See [The radio as a status line](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#the-radio-as-a-status-line).

### A STARS-like DCB bar

See [A STARS-like DCB bar](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skin-Authoring#a-stars-like-dcb-bar).

## Schema maintenance

The schema is a pinned copy (`tools/interface_contract/contract.json` names the game commit). Maintainers refresh
it with `python tools/sync_interface_contract.py --game <game checkout> --ref origin/closed-beta`, then
`python tools/skin_reference.py` to regenerate the key reference; a test fails if either copy is edited by hand.
The copies must retain the pinned game's exact bytes, including whitespace. `.prettierignore` excludes
`tools/interface_contract/`, and the formatting job runs the skin tests before committing. If a formatter
changes a copy, re-run the sync at the recorded `game_commit`; do not update its hash to accept the changed bytes.
