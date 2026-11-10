# MVA Sources

Every `mva.json` here is generated from a published chart by a tool in `tools/`; never edit one by hand.
This page lists the chart behind each generated file, how to rebuild it, and the choices each tool makes.

The game takes the highest MVA among the areas that contain a point and has no polygon holes. Both
tools follow the same rule, in `tools/mva_geometry.py`: a hole is dropped when everything inside it is
at least as high, and an area with a lower area (or no area) inside a hole is cut into hole-free
pieces. A cut shows on the scope as a line the chart does not have.

The same holds for whole areas: a lower area drawn wholly inside a higher one (a control zone inside
its TMA) is cut out of the higher area, or the game reads the higher value over it. The validator
refuses such a file, and `tools/mva_unhide.py <mva.json> --write` fixes it, checking on a 0.25 NM
grid that the game then reads the innermost area's value and nothing else changes. Amsterdam,
Gothenburg, Stockholm, Palma and Istanbul were fixed this way on 2026-11-10.

## United States: FAA AIXM

The FAA publishes each TRACON's MVA chart as AIXM 5.1 at <https://aeronav.faa.gov/MVA_Charts/aixm/>,
with the matching PDF under `pdf/`. The index page is
<https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/mva_mia/mva/>. It is US
government data. The FAA's release memo says the files are a visual reference, not for navigation.

`tools/faa_mva_aixm.py` reads the sector polygons exactly, so the file is the chart, not a tracing.
It writes the facility's whole chart, one area per sector, labelled with the altitude in full feet.
Take the `FUS3` file (3 NM separation, the one terminal controllers use near the field) when the
facility publishes one.

```
pip install shapely numpy
python tools/faa_mva_aixm.py N90_MVA_FUS3.xml --airport KJFK --out K/KZNY/JFK_TMA/mva.json --check
npx prettier --write K/KZNY/JFK_TMA/mva.json
```

`--check` replays the game's lookup over a 0.25 NM grid and exits 1 unless it agrees with the chart
at every point. Every file below reports 0 mismatches.

| File | Airport | Facility | Chart version | Source |
|------|---------|----------|---------------|--------|
| `K/KZNY/JFK_TMA/mva.json` | KJFK | N90 | `N90_MVA_FUS3_2025_v1` | <https://aeronav.faa.gov/MVA_Charts/aixm/N90_MVA_FUS3.xml> |
| `K/KZNY/LAGUARDIA_TMA/mva.json` | KLGA | N90 | `N90_MVA_FUS3_2025_v1` | <https://aeronav.faa.gov/MVA_Charts/aixm/N90_MVA_FUS3.xml> |
| `K/KZNY/NEWARK_TMA/mva.json` | KEWR | N90 | `N90_MVA_FUS3_2025_v1` | <https://aeronav.faa.gov/MVA_Charts/aixm/N90_MVA_FUS3.xml> |
| `K/KZBW/BOSTON_TMA/mva.json` | KBOS | A90 | `A90_MVA_FUS3_2024` | <https://aeronav.faa.gov/MVA_Charts/aixm/A90_MVA_FUS3.xml> |
| `K/KZDC/WASHINGTON_DCA_TMA/mva.json` | KDCA | PCT | `PCT_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/PCT_MVA_FUS3.xml> |
| `K/KZDC/DULLES_TMA/mva.json` | KIAD | PCT | `PCT_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/PCT_MVA_FUS3.xml> |
| `K/KZTL/ATLANTA_TMA/mva.json` | KATL | A80 | `A80_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/A80_MVA_FUS3.xml> |
| `K/KZAU/CHICAGO_ORD_TMA/mva.json` | KORD | C90 | `C90_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/C90_MVA_FUS3.xml> |
| `K/KZFW/DFW_TMA/mva.json` | KDFW | D10 | `D10_MVA_FUS3_2024` | <https://aeronav.faa.gov/MVA_Charts/aixm/D10_MVA_FUS3.xml> |
| `K/KZDV/DENVER_TMA/mva.json` | KDEN | D01 | `D01_DEN_PUB_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/D01_DEN_PUB_MVA_FUS3.xml> |
| `K/KZLA/LAX_TMA/mva.json` | KLAX | SCT | `SCT_MVA_FUS3_2025_v1` | <https://aeronav.faa.gov/MVA_Charts/aixm/SCT_MVA_FUS3.xml> |
| `K/KZLA/SAN_DIEGO_TMA/mva.json` | KSAN | SCT | `SCT_MVA_FUS3_2025_v1` | <https://aeronav.faa.gov/MVA_Charts/aixm/SCT_MVA_FUS3.xml> |
| `K/KZOA/SFO_TMA/mva.json` | KSFO | NCT | `NCT_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/NCT_MVA_FUS3.xml> |
| `K/KZSE/SEATTLE_TMA/mva.json` | KSEA | S46 | `S46_MVA_FUS3_2024` | <https://aeronav.faa.gov/MVA_Charts/aixm/S46_MVA_FUS3.xml> |
| `K/KZMA/MIAMI_TMA/mva.json` | KMIA | MIA | `MIA_MVA_FUS3_2025_v2` | <https://aeronav.faa.gov/MVA_Charts/aixm/MIA_MVA_FUS3.xml> |
| `K/KZJX/ORLANDO_TMA/mva.json` | KMCO | F11 | `F11_MVA_FUS3_2024` | <https://aeronav.faa.gov/MVA_Charts/aixm/F11_MVA_FUS3.xml> |
| `K/KZLA/LAS_TMA/mva.json` | KLAS | L30 | `L30_MVA_FUS3_2024` | <https://aeronav.faa.gov/MVA_Charts/aixm/L30_MVA_FUS3.xml> |
| `K/KZAB/PHOENIX_TMA/mva.json` | KPHX | P50 | `P50_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/P50_MVA_FUS3.xml> |
| `K/KZHU/HOUSTON_IAH_TMA/mva.json` | KIAH | I90 | `I90_MVA_FUS3_2025_v1` | <https://aeronav.faa.gov/MVA_Charts/aixm/I90_MVA_FUS3.xml> |
| `K/KZTL/CHARLOTTE_TMA/mva.json` | KCLT | CLT | `CLT_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/CLT_MVA_FUS3.xml> |
| `K/KZMP/MINNEAPOLIS_TMA/mva.json` | KMSP | M98 | `M98_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/M98_MVA_FUS3.xml> |
| `K/KZOB/DETROIT_TMA/mva.json` | KDTW | D21 | `D21_MVA_FUS3_2024` | <https://aeronav.faa.gov/MVA_Charts/aixm/D21_MVA_FUS3.xml> |
| `K/KZNY/PHILADELPHIA_TMA/mva.json` | KPHL | PHL | `PHL_MVA_FUS3_2024` | <https://aeronav.faa.gov/MVA_Charts/aixm/PHL_MVA_FUS3.xml> |
| `K/KZLC/SALT_LAKE_TMA/mva.json` | KSLC | S56 | `S56_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/S56_MVA_FUS3.xml> |
| `P/PA/PAZA/ANCHORAGE_TMA/mva.json` | PANC | A11 | `A11_MVA_FUS3_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/A11_MVA_FUS3.xml> |
| `P/PH/PHZH/PHNL_TMA/mva.json` | PHNL | ZHN | `ZHN_HNL ASR9_MVA_2025` | <https://aeronav.faa.gov/MVA_Charts/aixm/ZHN_HNL_ASR9_MVA.xml> |
Honolulu publishes no FUS3 chart; its file comes from the ASR-9 chart, the one covering the field.

Charts that needed cuts, because a lower sector sits inside a higher one: PCT (`NHK-A`), D10 (`A`),
I90 (`C`), D21 (`B`) and S56 (`F75`).

## France: AIP vector charts

France publishes one minimum vectoring altitude chart per airport, so each Paris airport has its own
`mva.json` in its airport folder. Both files are generated from the vector PDF of the chart by
`tools/aip_mva_chart.py`.

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

### How the chart is read

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
- On LFPO the 3000 ft ring around the 2000 ft area is cut into `3000_1` and `3000_2`; the cut lines are
  not chart borders.
