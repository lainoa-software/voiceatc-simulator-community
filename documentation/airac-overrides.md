# AIRAC variants

Aviation files can use a shared default and complete replacements for **Bundled**
and **Latest**. These names follow the databases included with the game and loaded
from a subscriber account. Do not use cycle numbers as override keys.

```json
{
  "airport": "EDDB",
  "runway_configs": [{ "id": "24", "arr": "24R 24L", "dep": "24R 24L" }],
  "airac_overrides": {
    "latest": {
      "airport": "EDDB",
      "runway_configs": [{ "id": "06", "arr": "06R 06L", "dep": "06R 06L" }]
    }
  }
}
```

This example demonstrates different content. It is not EDDB's operational file.
EDDB's shared default contains both `24` and `06`, with both parallel runways for
arrivals and departures. Neither tier requires a replacement for that correction.

## File contract

Only `bundled` and `latest` are accepted in `airac_overrides`. Each value must be a
complete, independently valid document of the same type and identity. Nested
`airac_overrides` are prohibited. A missing replacement uses the shared default.
An existing replacement replaces the whole document; it never merges with the
default. Empty content follows the existing rules for that file type.

Supported files: `runway_configs.json`, `procedure_options.json`, `constraints.json`,
`mva.json`, `sector_configs.json`, `sector_definitions.json`, `sector_influence.json`,
`misc_drawings.json`, `visual_procedures.json`, `visual_go_arounds.json`, and
`visual_sight_references.json`. Routes, colors and styles are unchanged.

Check references in both resolved tiers. A visual sidecar must refer to a procedure
in the matching visual document. Configuration references must refer to the matching
runway configuration document. A change to one file can require a change to its
related files. Run each affected manifest validator and the community tests.

## Editors and cycle changes

The runway and visual-procedure editors have **Shared default**, **Bundled**, and
**Latest** views. Add a replacement to copy the shared default into that tier.
Remove it to restore inheritance. Other file types are edited as JSON.

The simulator selects the tier from its loaded database and keeps it fixed for an
active flight. Subscription entitlement does not select a tier. The tier names
follow future database cycles automatically. Contributors must maintain the
aviation content; a rollover does not rename runways or procedures.

## Publication and compatibility

The `community.airac_overrides` capability gates complete documents. Publication
produces separate default-only documents for legacy clients and hashes their own
bytes. Full ZIP feeds contain the default entry before the capable entry. Sector
legacy paths remain scope-relative; capable files use generated variant aliases.
Raw-file datasets publish full and default manifests. Original source files are
never overwritten by compatibility output.

Release the simulator readers before enabling website submissions with variants.
Deploy the website after reader support reaches the selected release channels.
Use capability names, never fixed game versions, for compatibility.

## Digit-free SID and STAR keys

A `procedure_options.json` key can name a SID or STAR without its revision digit:
the exit or entry fix as in the AIP, a dot, then the route letter. `MARUN.E` is MARUN
5E on the bundled database and MARUN 6E on the latest. The simulator also matches the
six-character coded name (MARU6E). Under `runways`, the procedure must serve that
runway. The key must match exactly one procedure; with none (the fix was renamed, the
procedure withdrawn) or several, the simulator logs the key and spawns nothing from it.
Exact names still work and win over a key that resolves to the same procedure.

Builds without the `community.procedure_route_keys` capability read a digit-free key
as a literal name. Until every live build has it, put the digit-free document in both
`bundled` and `latest` and keep exact names in the shared default, which those builds
receive. The validator rejects digit-free keys in the shared default, and the full
procedure-options manifest requires the capability. EDDF's file is the example.
