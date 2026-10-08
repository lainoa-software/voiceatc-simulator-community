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
| 22 | LCPH | ESERI RNAV-to-Visual RWY 29 | RF legs and a defined visual-reference point |
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
- successful schema validation and a simulator preview to the exact navdata
  runway threshold.

If a chart is withdrawn, cannot be authoritatively accessed, or cannot be
represented safely by schema v1, replace it in this order: Waialae Golf Course
Visual PHNL, Bridge Visual TJSJ, Columbia Visual KPDX, Harbor Visual KBFI,
Belmont Visual KJFK.

## Completed authority audit

Source review completed 24 August 2026. FAA cycle 2608 remains effective
through 3 September 2026; affected FAA plates require another check after that
date. `Pass` means route order, branches, schema-v1 constraints, official
provenance, and the simulator-owned threshold boundary match the authority
source.

| Airport | Official procedure source | Result |
|---|---|---|
| KASE | [Roaring Fork RWY 15](https://aeronav.faa.gov/d-tpp/2608/05889ROARINGFORK_VIS15.PDF) | Corrected: seven arms and entry altitudes. |
| KBFI | [Harbor RWY 14R](https://aeronav.faa.gov/d-tpp/2608/00384HARBOR_VIS14R.PDF) | Pass: three branches. |
| KBOS | [Light RWY 33L](https://aeronav.faa.gov/d-tpp/2608/00058LIGHT_VIS33L.PDF) | Corrected LYHTT and the BOS 10 DME constraint. |
| KDCA | [Mount Vernon RWY 01](https://aeronav.faa.gov/d-tpp/2608/00443MOUNTVERNON_VIS1.PDF) | Corrected: one forward-join route; BADDN remains the last authored anchor before the simulator-owned threshold. |
| KDCA | [River RWY 19](https://aeronav.faa.gov/d-tpp/2608/00443RIVER_VIS19.PDF) | Corrected: GREYZ/RORRK river joins, charted 1800/1500/900 profile, and bridge anchors verified against official DDOT lines; route clears P-56. |
| KEWR | [Stadium RWY 29](https://aeronav.faa.gov/d-tpp/2608/00285STADIUM_VIS29.PDF) | Pass; published route constraints verified. |
| KJFK | [Parkway RWY 13L/R](https://aeronav.faa.gov/d-tpp/2608/00610PARKWAY_VIS13LR.PDF) | Corrected Rockaway abeam cue. |
| KLGA | [Park RWY 31](https://aeronav.faa.gov/d-tpp/2608/00289PARK_VIS31.PDF) | Corrected recommended profile and sight cue. |
| KLGB | [LA River RWY 12](https://aeronav.faa.gov/d-tpp/2608/00236LARIVER_VIS12.PDF) | Pass: both entries. |
| KLSV | [Sin City RWY 03L/R](https://aeronav.faa.gov/d-tpp/2608/00227SINCITY_VIS3LR.PDF) | Pass: AF arc and speed. |
| KPDX | [Columbia RWY 10L/R](https://aeronav.faa.gov/d-tpp/2608/00330COLUMBIA_VIS10LR.PDF) | Pass: four variants. |
| KPHL | [River RWY 09L/R](https://aeronav.faa.gov/d-tpp/2608/00320RIVER_VIS9LR.PDF) | Pass. |
| KSAN | [Sweetwater RWY 27](https://aeronav.faa.gov/d-tpp/2608/00373SWEETWATER_VIS27.PDF) | Corrected east-to-west branch; OKAIN retained. |
| KSEA | [Bay RWY 16R/C/L](https://aeronav.faa.gov/d-tpp/2608/00582BAY_VIS16RCL.PDF) | Pass: three runways. |
| KSFO | [Quiet Bridge RWY 28R](https://aeronav.faa.gov/d-tpp/2608/00375QUIETBRIDGE_VIS28R.PDF) | Pass; parallel-arrival geometry verified. |
| KSFO | [Tipp Toe RWY 28L/R](https://aeronav.faa.gov/d-tpp/2608/00375TIPPTOE_VIS28LR.PDF) | Pass; Class B profile retained. |
| LCLK | [ADLAS RWY 22](https://www.mcw.gov.cy/mcw/dca/ais/ais.nsf/All/455773618044F4C9C2257C7E00234503/$file/LC_Amdt_A_2026_003_en.pdf?OpenElement) | Pass. |
| LCPH | [ESERI RWY 29](https://www.mcw.gov.cy/mcw/dca/ais/ais.nsf/All/455773618044F4C9C2257C7E00234503/$file/LC_Amdt_A_2026_003_en.pdf?OpenElement) | Pass. |
| LFMN | [Environment RWY 04](https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_01_OCT_2026/FRANCE/AIRAC-2026-10-01/html/eAIP/Cartes/LFMN/AD_2_LFMN_ENV_01.pdf) | Corrected MN04A/QFU and DME restrictions. Rechecked 8 Oct 2026: the chart publishes no altitude at MN04A; its 5000 ft is the minimum height over land (ASFC), so the offshore point carries none. |
| LLBG | [GAVRI RWY 30](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLBG_VAC_30-2_V1_en.pdf) | Pass. |
| LLBG | [NAMIM RWY 21](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLBG_VAC_21NAMIM_V1_en.pdf) | Corrected TADOV/GINTU windows. |
| LLBG | [ROMIE RWY 30](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLBG_VAC_30-3_v1_en.pdf) | Corrected BG303 window. |
| LLER | [ADIVI RWY 01](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLER_VAC-01-1_V1_en.pdf) | Pass. |
| LLER | [NURIT RWY 19](https://e-aip.azurefd.net/2026-08-06-AIRAC/graphics/eAIP/LL_AD_2_LLER_VAC-19-1_V2_en.pdf) | Published go-around route retained in the additive sidecar. |
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

## Sight-reference audit (2 September 2026)

All 54 variants were checked independently for a static object that current
clients can ask the pilot to report. The audit used the official procedure
products listed above and, for FAA charted visual procedures, the reporting
rule in [FAA JO 7110.65 7-4-5](https://www.faa.gov/air_traffic/publications/atpubs/atc_html/chap7_section_4.html).
FAA cycle 2608 was current on the check date and expires 3 September 2026, so
these entries require the normal cycle recheck before a later merge or release.

`Published` means the sidecar deliberately maps the cited object to its own
airport, runway, point, or visible-route geometry. `Withheld` means the route
data remains in schema v1 for older clients, but current clients do not expose
that named variant. A label, nearby fix, or approximate point was never promoted
to evidence.

| Airport | Procedure / variant | Result |
|---|---|---|
| KBOS | Light / `LIGHT_VISUAL_MAIN` | **Published:** Boston Light at `LYHTT`. |
| KDCA | Mount Vernon / `MOUNT_VERNON_FORWARD_RIVER` | **Published:** Potomac River abeam Mount Vernon at the chart-traced point. |
| KDCA | River / `FORWARD_RIVER_ROUTE` | **Published:** ordered Potomac River route. |
| KASE | Roaring Fork / `DBL_R163_ENTRY` | **Published:** Aspen. |
| KASE | Roaring Fork / `CARBONDALE_BASALT_ENTRY` | **Published:** Carbondale. |
| KASE | Roaring Fork / `MT_SOPRIS_ENTRY` | **Published:** Mount Sopris. |
| KASE | Roaring Fork / `CAPITAL_PEAK_ENTRY` | **Published:** Capital Peak. |
| KASE | Roaring Fork / `CASTLE_PEAK_ENTRY` | **Published:** Castle Peak. |
| KASE | Roaring Fork / `INDEPENDENCE_PASS_ENTRY` | **Published:** Independence Pass. |
| KASE | Roaring Fork / `HOLY_CROSS_RUEDI_ENTRY` | **Published:** Mount of the Holy Cross. |
| KLSV | Sin City / `SIN_CITY_03L` | **Published:** northwest Las Vegas city outline, the plate's required report. |
| KLSV | Sin City / `SIN_CITY_03R` | **Published:** northwest Las Vegas city outline, the plate's required report. |
| KLGB | LA River / `PADDR_ENTRY` | **Published:** Vincent Thomas Bridge. |
| KLGB | LA River / `ALBAS_ENTRY` | **Published:** Queen Mary. |
| KSAN | Sweetwater / `MZB_R084_EAST_BRANCH` | **Published:** Mount Helix. |
| KSAN | Sweetwater / `OKAIN_ENTRY` | **Withheld:** the authored branch contains only OKAIN and CIJHI fixes; no independently located static sight object is supported. |
| KJFK | Parkway / `PARKWAY_13L` | **Published:** Twin Stacks. |
| KJFK | Parkway / `PARKWAY_13R` | **Published:** Canarsie Pier. |
| KLGA | Park / `PARKWAY_VISUAL_ROUTE` | **Published:** Twin White Tanks by default, plus the separately located airport. Preceding traffic is excluded. |
| KEWR | Stadium / `STADIUM_MAIN` | **Published:** Meadowlands Sports Complex at `GIMEE`. |
| KPHL | River / `RIVER_09L` | **Published:** Delaware River. |
| KPHL | River / `RIVER_09R` | **Published:** Delaware River. |
| KSFO | Quiet Bridge / `SOUTH_ENTRY` | **Withheld:** RAACL is charted 0.1 NM southeast of the San Mateo Bridge, not at the bridge itself. |
| KSFO | Quiet Bridge / `EAST_ENTRY` | **Withheld:** RAACL is charted 0.1 NM southeast of the San Mateo Bridge, not at the bridge itself. |
| KSFO | Tipp Toe / `TIPP_TOE_28L` | **Withheld:** the route has no authored landmark leg or independent official coordinate for either charted bridge. |
| KSFO | Tipp Toe / `TIPP_TOE_28R` | **Withheld:** the route has no authored landmark leg or independent official coordinate for either charted bridge. |
| KPDX | Columbia / `SAUVIE_10L` | **Published:** Interstate Five Bridge. |
| KPDX | Columbia / `SAUVIE_10R` | **Published:** Interstate Five Bridge. |
| KPDX | Columbia / `SCAPPOOSE_10L` | **Published:** Interstate Five Bridge. |
| KPDX | Columbia / `SCAPPOOSE_10R` | **Published:** Interstate Five Bridge. |
| KBFI | Harbor / `NORTHWEST_HOOD_CANAL` | **Published:** Harbor Island. |
| KBFI | Harbor / `NORTH_LAKE_WASHINGTON` | **Published:** Harbor Island. |
| KBFI | Harbor / `SOUTH_VASHON` | **Published:** Harbor Island. |
| KSEA | Bay / `BAY_16R` | **Published:** middle Elliott Bay. |
| KSEA | Bay / `BAY_16C` | **Published:** middle Elliott Bay. |
| KSEA | Bay / `BAY_16L` | **Published:** middle Elliott Bay. |
| LCLK | ADLAS / `LCLK_RWY22_ADLAS` | **Withheld:** the linked amendment does not publish a reportable static object for this visual segment. |
| LCPH | ESERI / `LCPH_RWY29_ESERI` | **Withheld:** the linked amendment does not publish a reportable static object for this visual segment. |
| LFMN | Environment / `LFMN_RWY04L` | **Withheld:** the environment chart defines operating limits but no reportable named object. |
| LFMN | Environment / `LFMN_RWY04R` | **Withheld:** the environment chart defines operating limits but no reportable named object. |
| LLER | ADIVI / `LLER_RWY01_ADIVI` | **Withheld:** the AIP requires visual reference to terrain but identifies no reportable static object. |
| LLER | NURIT / `LLER_RWY19_NURIT` | **Withheld:** the AIP requires visual reference to terrain but identifies no reportable static object. |
| LLBG | GAVRI / `LLBG_RWY30_GAVRI` | **Withheld:** the AIP requires visual reference to terrain at GAVRI, not sight of a named object. |
| LLBG | NAMIM / `LLBG_RWY21_NAMIM_TADOV` | **Withheld:** the AIP requires visual reference to terrain at NAMIM, not sight of a named object. |
| LLBG | NAMIM / `LLBG_RWY21_NAMIM_GINTU` | **Withheld:** the AIP requires visual reference to terrain at NAMIM, not sight of a named object. |
| LLBG | ROMIE / `LLBG_RWY30_ROMIE` | **Withheld:** the AIP requires visual reference to terrain at ROMIE, not sight of a named object. |
| LPMA | Visual RWY 05 / `LPMA_RWY05` | **Withheld:** the visual landing chart provides terrain and pattern guidance but no reportable sight object. |
| PANC | Highway / `LITTLE_SUSITNA_ENTRY` | **Published:** mouth of the Little Susitna River at `OSPUF`. |
| PANC | Highway / `POINT_POSSESSION_ENTRY` | **Published:** Point Possession at `MOPMY`. |
| PHOG | Smoke Stack / `LANAI_ENTRY` | **Published:** Sugar Mill Smoke Stacks. |
| PHOG | Smoke Stack / `MAKENA_ENTRY` | **Published:** Sugar Mill Smoke Stacks. |
| PHNL | Kahe Power Plant / `KAHE_MAIN` | **Published:** Kahe Power Plant. |
| PHNL | Waialae Golf Course / `WAIALAE_MAIN` | **Published:** Waialae Golf Course. |
| TJSJ | Bridge / `BRIDGE_MAIN` | **Withheld:** the authored point is the base east of Moscoso Bridge, not the bridge's own location. |

Audit total: **37 published, 17 withheld, 54 reviewed**. Route-data
discrepancies remain separate work; no schema-v1 route was silently moved to
make a sight target pass.

Do not substitute retired Kai Tak procedures, scenic ordinary visuals, VFR or
AFIS landing routes, contact or circling approaches, traffic-following visual
separation, or an instrument procedure that merely ends visually.
