# Agent instructions for VoiceATC Simulator Community

This repository holds community-authored data that VoiceATC Simulator downloads: airports, runway
configurations, procedures, sectors, radar displays, colours and published flight routes. It is public. Every
file, commit and pull request here can be read by anyone.

## Read first

- [README.md](README.md) for the task map and where each kind of file goes.
- [documentation/CONTENT_HIERARCHY.md](documentation/CONTENT_HIERARCHY.md), the machine-backed placement rules
  the validators enforce. [content_hierarchy.json](documentation/content_hierarchy.json) is the registry.
- The [contributor wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki) page for the file
  type you change. It owns the file formats and the per-file validator list.

## Check before a pull request

Run, from the repository root with Python 3.11 or newer:

```text
python tools/validate_all.py
```

It runs every command of the required `validate` job, read from
`.github/workflows/validate-content-hierarchy.yml`, unit tests included. Every check must pass. A pull request
needs the `validate` check and one approving review before it merges into `main`.

## Do not touch

- `.voiceatc/`: generated manifests and indexes. CI and the daily release workflow write them.
- JSON formatting: CI formats JSON with Prettier. Change data, not layout.
- `K/KA` to `K/KZ` colour or style files: the release projects them from `K/colors.json` and `K/style.json`, and
  validation rejects them in the source tree.
- The contributor wiki is a separate git repository (`voiceatc-simulator-community.wiki`) with no review. A push
  publishes immediately, so push only finished pages.

## Content rules

- Keep each change focused. Name its public authoritative source (chart, AIP, published procedure) in the pull
  request.
- Nothing private goes into this repository: no credentials, no local paths, no private repositories or
  documents, no private data sources.
- Commits and pull requests carry no AI co-author trailer and no "generated with" footer.

## Sessions

Edit only a worktree of your own, never the shared main clone. Branch from a fresh `origin/main`, run
`python tools/validate_all.py` in the worktree, open a pull request to `main` and remove the worktree once it
merges.
