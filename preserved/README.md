# Preserved legacy sector files

These files are verbatim copies from main prior to the schema-2 migration.
They are **read by nothing in the game** and exist solely so modder progress
present only in the ignored legacy files is not lost.

During the schema-2 migration, three bundles were classified as
**Class 2 (content only in the copy)** in the migration divergence audit:
whenever 	ma.json existed, the game skipped sector_configs.json and
sector_influence.json, so any sectors, layouts, or influenced airports
written only in those legacy copies were ignored at runtime:

- E/ED/EDMM/EDDM_TMA: legacy sector_configs.json layouts 1, 2, 3
  with sectors DMNAT, DMNH, DMNL, DMSAT, DMSH, DMSL and
  sector_influence.json airports EDMA, EDMO absent from 	ma.json.
- L/LE/LECB/LECB_W/BARCELONA_TMA: legacy sector_configs.json layouts 1W
  (LEGEAPP) and 1E (LERSAPP) and sector_influence.json airports
  LELL, LESU (LEBLCORE), LEGE (LEGEAPP), LERS (LERSAPP).
- L/LE/LECM/LECM_R2/MADRID_TMA: legacy sector_configs.json layout 1 and
  sector_influence.json airports LECU, LEGT, LETO (LEMDALN).
