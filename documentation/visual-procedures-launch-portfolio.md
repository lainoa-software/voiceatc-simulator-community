# Visual procedures 0.6.2 launch portfolio

This is the authoring order for the first reviewed visual-procedure library.
It is a priority list, not a popularity claim. The ranking weights public fame,
current operational authenticity, gameplay distinctiveness, geographic
diversity, and transcription feasibility.

The infrastructure pull request deliberately contains no route geometry.
After it merges, contributors submit the list as 24 airport-level pull
requests: procedures sharing an airport stay in one `visual_procedures.json`.
Every row must be rechecked against the current official chart immediately
before it is transcribed.

The 24 August 2026 source gate could not inspect current authoritative plates
for the two Japan procedures or NAV CANADA's GOWER chart. France SIA's LFBD
environment chart could not be represented safely without inventing unnamed
radial geometry. In accordance with the fallback order below, ranks 2, 5, 6,
and 9 use Waialae Golf Course, Bridge, Columbia, and Harbor respectively; no
geometry was inferred from mirrors or incomplete chart cues.

## Ranked procedures

| # | Airport | Procedure | Signature gameplay |
|---:|---|---|---|
| 1 | KDCA | River Visual RWY 19 | Potomac corridor and restricted-airspace discipline |
| 2 | PHNL | Waialae Golf Course Visual | Oahu shoreline and golf-course landmark routing |
| 3 | KLGA | Park Visual RWY 31 | Dense urban landmarks and curved final |
| 4 | KASE | Roaring Fork Visual RWY 15 | Mountain-valley route and strict chart conditions |
| 5 | TJSJ | Bridge Visual | San Juan shoreline and bridge landmark routing |
| 6 | KPDX | Columbia Visual | Columbia River routing and Portland landmarks |
| 7 | LPMA | Visual Approach RWY 05 | Coastal turn with close terrain |
| 8 | LFMN | Environment Visual RWY 04 | Offshore routing and populated-area avoidance |
| 9 | KBFI | Harbor Visual | Seattle harbour and shoreline routing |
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

## Completed authority audit

Source review completed 24 August 2026. FAA cycle 2608 remains effective
through 3 September 2026; affected FAA plates require another check after that
date. `Pass` means route order, branches, schema-v1 constraints, availability
facts, and the simulator-owned threshold boundary match the authority source.

| Airport | Official procedure source | Result |
|---|---|---|
| KASE | [Roaring Fork RWY 15](https://aeronav.faa.gov/d-tpp/2608/05889ROARINGFORK_VIS15.PDF) | Corrected: seven arms and entry altitudes. |
| KBFI | [Harbor RWY 14R](https://aeronav.faa.gov/d-tpp/2608/00384HARBOR_VIS14R.PDF) | Pass: three branches. |
| KBOS | [Light RWY 33L](https://aeronav.faa.gov/d-tpp/2608/00058LIGHT_VIS33L.PDF) | Corrected LYHTT and BOS 10 DME note. |
| KDCA | [Mount Vernon RWY 01](https://aeronav.faa.gov/d-tpp/2608/00443MOUNTVERNON_VIS1.PDF) | Corrected: one river route and forward join. |
| KDCA | [River RWY 19](https://aeronav.faa.gov/d-tpp/2608/00443RIVER_VIS19.PDF) | Corrected: complete upper-river corridor and P-56 note. |
| KEWR | [Stadium RWY 29](https://aeronav.faa.gov/d-tpp/2608/00285STADIUM_VIS29.PDF) | Pass; source cautions retained. |
| KJFK | [Parkway RWY 13L/R](https://aeronav.faa.gov/d-tpp/2608/00610PARKWAY_VIS13LR.PDF) | Corrected Rockaway abeam cue. |
| KLGA | [Park RWY 31](https://aeronav.faa.gov/d-tpp/2608/00289PARK_VIS31.PDF) | Corrected recommended profile and sight cue. |
| KLGB | [LA River RWY 12](https://aeronav.faa.gov/d-tpp/2608/00236LARIVER_VIS12.PDF) | Pass: both entries. |
| KLSV | [Sin City RWY 03L/R](https://aeronav.faa.gov/d-tpp/2608/00227SINCITY_VIS3LR.PDF) | Pass: AF arc and speed. |
| KPDX | [Columbia RWY 10L/R](https://aeronav.faa.gov/d-tpp/2608/00330COLUMBIA_VIS10LR.PDF) | Pass: four variants. |
| KPHL | [River RWY 09L/R](https://aeronav.faa.gov/d-tpp/2608/00320RIVER_VIS9LR.PDF) | Pass. |
| KSAN | [Sweetwater RWY 27](https://aeronav.faa.gov/d-tpp/2608/00373SWEETWATER_VIS27.PDF) | Corrected east-to-west branch; OKAIN retained. |
| KSEA | [Bay RWY 16R/C/L](https://aeronav.faa.gov/d-tpp/2608/00582BAY_VIS16RCL.PDF) | Pass: three runways. |
| KSFO | [Quiet Bridge RWY 28R](https://aeronav.faa.gov/d-tpp/2608/00375QUIETBRIDGE_VIS28R.PDF) | Pass; radar/parallel notes retained. |
| KSFO | [Tipp Toe RWY 28L/R](https://aeronav.faa.gov/d-tpp/2608/00375TIPPTOE_VIS28LR.PDF) | Pass; Class B profile retained. |
| LCLK | [ADLAS RWY 22](https://www.mcw.gov.cy/mcw/dca/ais/ais.nsf/All/455773618044F4C9C2257C7E00234503/$file/LC_Amdt_A_2026_003_en.pdf?OpenElement) | Pass. |
| LCPH | [ESERI RWY 29](https://www.mcw.gov.cy/mcw/dca/ais/ais.nsf/All/455773618044F4C9C2257C7E00234503/$file/LC_Amdt_A_2026_003_en.pdf?OpenElement) | Pass. |
| LFMN | [Environment RWY 04](https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_06_AUG_2026/FRANCE/AIRAC-2026-08-06/html/eAIP/Cartes/LFMN/AD_2_LFMN_ENV_01.pdf) | Corrected MN04A/QFU and DME restrictions. |
| LLBG | [GAVRI RWY 30](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLBG_VAC_30-2_V1_en.pdf) | Pass. |
| LLBG | [NAMIM RWY 21](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLBG_VAC_21NAMIM_V1_en.pdf) | Corrected TADOV/GINTU windows. |
| LLBG | [ROMIE RWY 30](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLBG_VAC_30-3_v1_en.pdf) | Corrected BG303 window. |
| LLER | [ADIVI RWY 01](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLER_VAC-01-1_V1_en.pdf) | Pass. |
| LLER | [NURIT RWY 19](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLER_VAC-19-1_V2_en.pdf) | Corrected missed-route speeds. |
| LPMA | [Visual RWY 05](https://ais.nav.pt/wp-content/uploads/AIS_Files/eAIP_Current/eAIP_Online/eAIP/graphics/eAIP/LP_AD_2_LPMA_13-1_en.pdf) | Pass. |
| PANC | [Highway RWY 25R](https://aeronav.faa.gov/d-tpp/2608/01500HIGHWAY_VIS25R.PDF) | Pass: two branches and AF arc. |
| PHNL | [Kahe Power Plant RWY 22L](https://aeronav.faa.gov/d-tpp/2608/00754KAHEPOWERPLANT_VIS22L.PDF) | Pass. |
| PHNL | [Waialae Golf Course RWY 22L](https://aeronav.faa.gov/d-tpp/2608/00754WAIALAEGOLFCOURSE_VIS22L.PDF) | Corrected Punchbowl abeam cue. |
| PHOG | [Smoke Stack RWY 02](https://aeronav.faa.gov/d-tpp/2608/00762SMOKESTACK_VIS2.PDF) | Pass: two branches. |
| TJSJ | [Bridge RWY 10](https://aeronav.faa.gov/d-tpp/2608/00784BRIDGE_VIS10.PDF) | Pass. |

The two KASE turn advisories at the common Aspen trace are accepted review
advice: the official plate is explicitly not to scale and publishes direct
landmark arms without authoritative intermediate coordinates. They remain
visible rather than being hidden with invented turn points.

Do not substitute retired Kai Tak procedures, scenic ordinary visuals, VFR or
AFIS landing routes, contact or circling approaches, traffic-following visual
separation, or an instrument procedure that merely ends visually.
