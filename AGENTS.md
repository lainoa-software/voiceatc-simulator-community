# Agents

Contributor rules live in [README.md](README.md), the
[contributor wiki](https://github.com/lainoa-software/voiceatc-simulator-community/wiki)
and [documentation/](documentation/). This page adds only what automated agents need.

## Validate

```sh
python tools/validate_all.py
```

Runs every check of the required `validate` CI job (tests, all validators, release
build and stable-contract guard) in about 15 s. Its commands come from
`.github/workflows/validate-content-hierarchy.yml`, so it cannot drift from CI. Each
validator checks the whole repository on purpose: cross-file rules such as duplicate
airports need every file.

## Content enumeration

Validators and manifest builders find content files through
`tools/content_files.py` only. It skips `.claude/`, `.git/`, `.voiceatc/`, `build/`,
`node_modules/` and the other directories listed there, relative to the checkout root.
Never add a new `rglob` walk; agent worktrees under `.claude/worktrees/` are full
repository copies and must never be scanned as content.

## Slow paths need a reason

Every serial, queued, capped or recompute-everything choice for independent work states
its reason: correctness, cross-file consistency, an external rate limit, RAM, or a dated
creator decision. Before accepting a slow path, check that the constraint actually exists.
