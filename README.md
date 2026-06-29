# VoiceATC Simulator Community
The Github to manage custom airports and sectors for VoiceATC Simulator.

## Contributing
To contribute, fork this repository, commit your changes there and then create a pull request onto the main repository. Read the wiki pages on this repository to gain knowledge on how to create or modify the airport of your liking.

## Pull Requests
In order to keep the reposititory organized, name all pull requests `[FIR/Airport] Updated/Fixed/Added...` - for example `[ESSA] Updated MVAs`. There are automatic checks that will be preformed when you create a pull request, and after those the files will be inspected by a maintainer before being merged. If any errors are spotted, we will ask you to update the pull request before we can merge it.

## Procedure options (`procedure_options.json`)
An optional per-airport file that records attributes for each of the airport's procedures. Place it in the airport's folder next to `constraints.json` (e.g. `R/RC/RCAA/TAIPEI_TMA/RCTP/procedure_options.json`).

Today it controls **which procedures the automatically generated traffic may be assigned**. It does **not** change what the controller can assign manually. Behaviour is opt-out: an airport with no file, and any procedure not listed, is treated as enabled — so adding the file never reduces traffic unless you explicitly disable something.

Keys are procedure idents as they appear in the navigation data (the same idents you see in-game), grouped into `stars`, `sids`, and `iaps`. Each procedure maps to an object so more attributes can be added later (for example a SID's initial climb).

```json
{
  "airport": "RCTP",
  "schema_version": 1,
  "airac_min": 2604,
  "defaults": { "spawn_enabled": true },
  "stars": {
    "GRAC1A": { "spawn_enabled": true },
    "TONG1B": { "spawn_enabled": false }
  },
  "sids": {},
  "iaps": {}
}
```

- `spawn_enabled: false` withholds a procedure from generated traffic. Resolution order per procedure: a matching per-runway override (see below), then its own global `spawn_enabled`, then `defaults.spawn_enabled`, then `true`.
- `defaults.spawn_enabled: false` flips the airport to allow-list style (disable everything, then enable only the listed procedures).
- `airport` must match the folder name. Run `python tools/procedure_options_manifest.py --validate-only` before opening a PR; the manifest is regenerated automatically on release.

### Per-runway overrides (`runways`)
Most procedures are already locked to one landing/departure direction by the navigation data, so the per-procedure flags above are usually enough. When a **shared** procedure (one that serves more than one direction) should be available for one runway but not another, add an optional top-level `runways` object. Each key is a bare runway token (e.g. `"25"`); its `stars`/`sids`/`iaps` use the same per-procedure shape and override the global flag **only** when that runway is active.

```json
{
  "airport": "EDDS",
  "schema_version": 1,
  "airac_min": 2604,
  "defaults": { "spawn_enabled": true },
  "stars": {
    "REUT5A": { "spawn_enabled": false }
  },
  "runways": {
    "25": { "stars": { "GEBN1W": { "spawn_enabled": true } } },
    "07": { "stars": { "GEBN1W": { "spawn_enabled": false } } }
  }
}
```

## Bugs, Suggestions & Feedback
Open Github issues regarding the issue, suggestion or feedback. Remember to explain it thoroughly so someone can help you.

## Discord
If you have more questions, send a message in the questions-channel in our Discord. https://discord.gg/Hr4Z8e3cyn

## License
[![CC BY-NC-SA 4.0][cc-by-nc-sa-shield]][cc-by-nc-sa]

This repository is licensed under a
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License][cc-by-nc-sa].

[![CC BY-NC-SA 4.0][cc-by-nc-sa-image]][cc-by-nc-sa]

[cc-by-nc-sa]: http://creativecommons.org/licenses/by-nc-sa/4.0/
[cc-by-nc-sa-image]: https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png
[cc-by-nc-sa-shield]: https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg
