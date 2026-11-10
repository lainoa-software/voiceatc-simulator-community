# France MVA Sources

France publishes one minimum vectoring altitude chart per airport, so each Paris airport has its own
`mva.json` in its airport folder. Both files are generated from the vector PDF of the chart by
`tools/aip_mva_chart.py`; never edit them by hand.

| File | Chart | Effective | Source |
|------|-------|-----------|--------|
| `L/LF/LFFF/PARIS_TMA/LFPG/mva.json` | AD 2 LFPG MVA 01 | 01 OCT 2026 (AIRAC 2026-10-29 eAIP) | <https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_29_OCT_2026/FRANCE/AIRAC-2026-10-29/html/eAIP/Cartes/LFPG/AD_2_LFPG_MVA_01.pdf> |
| `L/LF/LFFF/PARIS_TMA/LFPO/mva.json` | AD 2 LFPO MVA 01 | 01 OCT 2026 (AIRAC 2026-10-29 eAIP) | <https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_29_OCT_2026/FRANCE/AIRAC-2026-10-29/html/eAIP/Cartes/LFPO/AD_2_LFPO_MVA_01.pdf> |

Regenerate after a new chart edition:

```
pip install pymupdf shapely fonttools numpy
python tools/aip_mva_chart.py AD_2_LFPG_MVA_01.pdf --airport LFPG --out L/LF/LFFF/PARIS_TMA/LFPG/mva.json --check-png lfpg.png
npx prettier --write L/LF/LFFF/PARIS_TMA/LFPG/mva.json
```

The tool refuses to write when a face has no label or conflicting labels. Open the `--check-png`
image and confirm every chart area appears once with its number.

## How the chart is read

- Areas are the faces of the thick black borders. Each takes the boxed label inside it, or at the end
  of the label's leader line. `FL070` is written as 7000 ft.
- Page points are georeferenced with a quadratic fit to the chart's 30-minute graticule (28 crossings,
  worst residual 0.18 NM).
- Boundary vertices with printed coordinates ("49 42 53 N 003 29 05 E") take the printed value. The
  drawn vertices sit 0.19 to 1.30 NM from their printed positions on both 01 OCT 2026 charts, so
  vertices without printed coordinates carry the chart's drawing accuracy, typically about 0.4 NM.
- P 23 is its own 2500 ft area. The game takes the highest MVA among the areas that contain a point,
  so it overlays the surrounding 2000 ft area.
- LFPG note (3) excludes the "RADAR" quadrilateral from the 1500 ft area. The chart draws it as a small
  ring and its coordinates are not published in the eAIP text, so the ring is written as a 2000 ft area,
  the MVA of the area around the 1500 ft area.
- An area that has a lower area nested inside it is cut into hole-free pieces, because the game has no
  polygon holes. On LFPO the 3000 ft ring around the 2000 ft area is written as `3000_1` and `3000_2`;
  the cut lines are not chart borders.
