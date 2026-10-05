# VoiceATC Simulator Community

Community-authored airports, sectors, radar displays, interface skins and flight routes
for VoiceATC Simulator. Accepted contributions reach the game after publication.

## Start here

The **[contributor wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki)**
walks through choosing a task, editing, local testing, validation and submission.

- [Getting started](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Getting-Started) — editor, Python, your fork and JSON basics.
- [Your first contribution](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Your-First-Contribution) — make and test a small runway-configuration edit.
- [Test locally](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Test-Locally) — exact game paths and expected results; no PR needed for supported local files.
- [Troubleshooting](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Troubleshooting) — find the selected file and resolve common failures.
- [Validate and submit](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Validate-and-Submit) — validators, new-airport registration, review and publication.

## Choose a task

| I want to… | Guide |
|---|---|
| Add airport data or change runway flows | [Airport](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Airport), [Runway Configs](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Runway-Configs) |
| Select procedures or initial climbs | [Procedure Options](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Procedure-Options) |
| Correct STAR restrictions | [Constraints](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Constraints) |
| Add a charted visual approach | [Visual Procedures](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Visual-Procedures) |
| Define airspace or radar geometry | [Sector Definitions](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Sector-Definitions), [MVA](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/MVA), [Misc Drawings](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Misc-Drawings) |
| Change radar colours or symbols | [Colours](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Colours), [Styles](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Styles) |
| Make an interface skin | [Skins](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Skins) |
| Share a flight route | [Routes](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Routes) — website workflow |

## Where your files go

[Content Hierarchy](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Content-Hierarchy)
explains repository placement. The game's local test folders are separate; use
[Test Locally](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Test-Locally)
instead of copying the repository root into the game directory.

## Contributing

Keep the change focused, cite its authoritative source and check it in the game.
The [submission guide](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Validate-and-Submit)
owns the command list. Contributors validate source data; CI formats JSON and maintains
generated indexes under `.voiceatc/`. Approval and a green required check are both needed.

## Reference

- [Hierarchy authority](documentation/CONTENT_HIERARCHY.md) — registry and placement contracts.
- [Visual-procedure contract](documentation/visual-procedures.md) — schema, source evidence and review.
- [Generated skin key reference](documentation/skins-reference.md) — every supported skin key.
- [US runway config sources](documentation/US_RUNWAY_CONFIG_SOURCES.md) — provenance of existing flows.

## Maintainers

- [Route publication](documentation/routes-publication.md).
- [Channel gates](documentation/channel-gates.md).
- [Catalog publication](documentation/skins-catalog.md#how-it-ships-maintainers).
- [Skin schema maintenance](documentation/skins-modding.md#schema-maintenance).

## Bugs, suggestions and feedback

Open a GitHub issue with the affected airport/file, expected result and observed behavior.
For installation help, start with [Troubleshooting](https://github.com/lainoa-software/voiceatc-simulator-community/wiki/Troubleshooting).

## Discord

Ask in the questions channel: https://discord.gg/Hr4Z8e3cyn

## License

This repository is licensed under
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/).
