# Visual procedures 0.6.2 launch portfolio

This is the authoring order for the first reviewed visual-procedure library.
It is a priority list, not a popularity claim. The ranking weights public fame,
current operational authenticity, gameplay distinctiveness, geographic
diversity, and transcription feasibility.

The infrastructure pull request deliberately contains no route geometry.
After it merges, contributors submit the list as 25 airport-level pull
requests: procedures sharing an airport stay in one `visual_procedures.json`.
Every row must be rechecked against the current official chart immediately
before it is transcribed.

## Ranked procedures

| # | Airport | Procedure | Signature gameplay |
|---:|---|---|---|
| 1 | KDCA | River Visual RWY 19 | Potomac corridor and restricted-airspace discipline |
| 2 | RJTT | Highway Visual RWY 34R | Tokyo Bay highway landmarks and parallel traffic |
| 3 | KLGA | Park Visual RWY 31 | Dense urban landmarks and curved final |
| 4 | KASE | Roaring Fork Visual RWY 15 | Mountain-valley route and strict chart conditions |
| 5 | RJFK | KINKO Visual RWY 34 | Sakurajima, coastline, radials, and altitude gates |
| 6 | CYVR | GOWER Visual entry RWY 12 | Bowen Island and Vancouver landmark routing |
| 7 | LPMA | Visual Approach RWY 05 | Coastal turn with close terrain |
| 8 | LFMN | Environment Visual RWY 04 | Offshore routing and populated-area avoidance |
| 9 | LFBD | Environment Visual RWY 05 | Prescribed environmental track |
| 10 | KSFO | Tipp Toe Visual RWY 28L/R | Bridges, altitude gates, and parallel finals |
| 11 | KPHL | River Visual RWY 09L/R | Delaware River alignment and runway branching |
| 12 | KSAN | Sweetwater Visual RWY 27 | Reservoir, mountain, and urban landmarks |
| 13 | KBOS | Light Visual RWY 33L | Lighthouse and harbour references |
| 14 | KLSV | Sin City Visual RWY 03L/R | Las Vegas landmarks and a DME arc |
| 15 | KLGB | LA River Visual RWY 12 | River, harbour, bridge, and Queen Mary routing |
| 16 | PHNL | Kahe Power Plant Visual RWY 22L | Island coast, power plant, and harbour references |
| 17 | LLER | ADIVI RNAV Visual RWY 01 | RNAV route into a terrain-visual final |
| 18 | LLER | NURIT RNAV Visual RWY 19 | Gulf routing and a published visual transition |
| 19 | LLBG | GAVRI Visual RWY 30 | RNAV visual track with altitude gates |
| 20 | LLBG | NAMIM Visual RWY 21 | Multi-fix RNAV visual route |
| 21 | LLBG | ROMIE Visual RWY 30 | Short alternate route with constraints |
| 22 | LCPH | ESERI RNAV-to-Visual RWY 29 | RF legs and a defined visual-availability point |
| 23 | LCLK | ADLAS RNAV-to-Visual RWY 22 | Coast and salt-lake routing |
| 24 | KSFO | Quiet Bridge Visual RWY 28R | Bridge reference and parallel-arrival geometry |
| 25 | KJFK | Parkway Visual RWY 13L/R | Belt Parkway and shoreline landmarks |
| 26 | KDCA | Mount Vernon Visual RWY 01 | Potomac routing from the south |
| 27 | KEWR | Stadium Visual RWY 29 | Stadium and urban alignment |
| 28 | KSEA | Bay Visual RWY 16R/C/L | Puget Sound routing with three runway variants |
| 29 | PANC | Highway Visual RWY 25R | Highway and coast references in Alaska |
| 30 | PHOG | Smoke Stack Visual RWY 02 | Maui coastal and industrial landmarks |

## Source review

Use the current product of the responsible authority. The initial research
used FAA d-TPP, MLIT Japan AIS, NAV CANADA, NAV Portugal, France SIA, Israel
eAIP, and Cyprus DCA AIS. A source being present during planning is not evidence
that it remains current when a data pull request is opened.

For every procedure, the pull request checklist must record:

- official authority, chart title, HTTPS source, effective date or AIRAC, and
  checked date;
- published entry and sight reference, every TF/CF/RF/AF leg, turn, and
  required versus recommended constraint;
- published availability notes without treating them as 0.6.2 runtime weather
  gates;
- successful schema validation and a simulator preview to the exact navdata
  runway threshold.

If a chart is withdrawn, cannot be authoritatively accessed, or cannot be
represented safely by schema v1, replace it in this order: Waialae Golf Course
Visual PHNL, Bridge Visual TJSJ, Columbia Visual KPDX, Harbor Visual KBFI,
Belmont Visual KJFK.

Do not substitute retired Kai Tak procedures, scenic ordinary visuals, VFR or
AFIS landing routes, contact or circling approaches, traffic-following visual
separation, or an instrument procedure that merely ends visually.
