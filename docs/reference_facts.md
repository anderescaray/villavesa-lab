# Reference facts: Pamplona TUC (villavesas)

Compiled 2026-11-10 from public web sources, for calibrating the villavesa-lab cost model and sanity checks.

Conventions used in every table:

- **Type**: `V` = figure read verbatim in a source document I opened and parsed; `D` = derived by me (arithmetic shown); `S` = reported only in a search-engine snippet or a secondary page I could not open (treat as unverified).
- **Confidence**: High / Medium / Low.
- Fetching notes: `noticiasdenavarra.com` and `navarra.es` blocked automated fetches (HTTP 406 / connection reset), and the old `infotuc.es/descargas/Dossier_Prensa/*.pdf` press dossier now returns 404 (site moved to `tuvillavesa.es`). Facts that only came from those sites are marked `S`.
- The 2024 MCP "Memoria / Informe de gestión" was **not found online** (the URL pattern `.../memoria2024/...` returns 404); the latest full management report found is **2023**.

Primary sources used repeatedly (abbreviations):

- **MCP-M23**: MCP, "Memoria 2023 - Informe de gestión - Transporte Urbano Comarcal", https://recursos-prod.mcp.es/memorias/memoria2023/es/informe-gestion-2023/transporte-urbano-comarcal.htm
- **XPLAN**: MCP, "X Plan 2023 de Transporte Urbano de la Comarca de Pamplona" (PDF), https://recursos-prod.mcp.es/transparencia/planificacion-estadistica/X%20Plan%20TUC%202023%20CAS.pdf
- **OMM**: Observatorio de la Movilidad Metropolitana, "Informe 2022-23" (data on 2022 and 2023, published 2026), https://observatoriomovilidad.es/wp-content/uploads/2026/03/2024-Datos-2022-23.pdf
- **MCP-SQ**: MCP web, "Sabias que...", https://www.mcp.es/transporte/habitos-responsables/sabias-que

---

## 1. Fleet and peak vehicle requirement

| Item | Value | Unit | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|---|
| Total buses | 159 | buses | 2022 and 2023 | V | MCP-M23 | High. |
| Standard 12 m | 93 (2022: 95) | buses | 2023 | V | MCP-M23 | High. |
| Articulated 18 m | 64 (2022: 62) | buses | 2023 | V | MCP-M23 | High. |
| Minibuses 9 m | 2 | buses | 2023 | V | MCP-M23 | High. |
| Hybrid / electric / CNG | 72 / 7 / 19 | buses | 2023 | V | MCP-M23 | High. Remainder (~61) not split in the report. |
| Low-floor share | 100% (159 of 159) | % | 2023 | V | MCP-M23; OMM also lists 100% PMR-equipped | High. |
| Average fleet age | 7.42 (2022: 7.05) | years | 2023 | V | MCP-M23 | High. |
| Fleet 2022 by length (OMM) | 2 / 95 / 62 / total 159 | buses | 2022 | V | OMM (Table of fleet, "C. de Pamplona") | High, matches MCP-M23. |
| Fleet mid-2026 | 172 total: 65 articulated, 105 rigid 12 m, 2 of 10 m | buses | 2026 | S | Search-engine summary of Noticias de Navarra, 2026-07-01 "La flota de villavesas incorpora 16 nuevos autobuses hibridos", https://www.noticiasdenavarra.com/navarra/comarca-de-pamplona/2026/07/01/flota-villavesas-incorpora-16-nuevos-autobuses-hibridos-11271839.html | **Low.** Could not open the article. A second search summary of the same article gave a powertrain split that sums to 149 (66 diesel-hybrid, 26 electric, 45 renewable gas, 12 gas-hybrid), which conflicts with 172. Do not use until verified. |
| Wikipedia infobox fleet | 171 (62 articulated, 44 combustion, 65 hybrid, 26 electric, 35 CNG) | buses | ~2024 | S | https://es.wikipedia.org/wiki/Transporte_Urbano_Comarcal_de_Pamplona | Low; secondary, internally inconsistent with MCP-M23. |
| Contract-planned fleet additions | 133 new buses over the 10-year contract (84 renewable-gas, 49 electric) | buses | 2023 tender | V (via trade press) | https://www.autobusesyautocares.com/texto-diario/mostrar/4311017/mcp-aprueba-pliego-licitar-transporte-urbano-comarcal-pamplona | Medium-High. |
| **Peak vehicle requirement (PVR)** | **not found** | | | | | Looked in: MCP-M23, XPLAN (full-text grep for "hora punta", "vehiculos necesarios", "flota maxima"), OMM, MCP/infotuc pages. Not published in the documents I could open. Fleet of 159 includes an unpublished reserve share; do not equate fleet with PVR. |

## 2. Annual vehicle-km and service hours

| Item | Value | Unit | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|---|
| Vehicle-km, total | 7,985,316 | km | 2023 | V | MCP-M23 | High. |
| - of which day + reinforcements | 7,678,483 | km | 2023 | V | MCP-M23 | High. |
| - of which night | 306,833 | km | 2023 | V | MCP-M23 | High. |
| Vehicle-km, total | 7,926,789 | km | 2022 | V | MCP-M23 | High. |
| Vehicle-km, total | 8,124,906 | km | 2024 | V | MCP-SQ ("en 2024 el total de kilometros realizados por las lineas del transporte urbano comarcal fue de 8.124.906") | High. Longest line L4: 1,129,642 km. |
| Vehicle-hours ("horas-vehiculo de servicio"), total | 624,817 | h | 2023 | V | MCP-M23 | High. |
| - day + reinforcements | 606,400 | h | 2023 | V | MCP-M23 | High. |
| - night | 21,417 | h | 2023 | V | MCP-M23 | High. |
| Vehicle-hours | 624,139 | h | 2022 | V | MCP-M23 | High. |
| Vehicle-hours 2024 | not found | h | 2024 | | | Looked in MCP-SQ, search for the 2024 memoria. Only km found for 2024. |
| Planned 2023 service in X Plan | K = 8,106,153.93 km; H = 641,258.11 h | km; h | 2023 plan | V | XPLAN section 5.2.1 | High (plan, not outturn). |
| km per vehicle-hour (implied) | 12.78 (7,985,316 / 624,817) | km/h | 2023 | D | from MCP-M23 | High. Note: the 12.70 km/h "commercial speed" is computed on useful (in-line) km and hours, so it is slightly lower than total km / total hours. |

## 3. Ridership

| Item | Value | Unit | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|---|
| Total trips ("viajes") | 46,055,590 (126,000/day average) | trips | 2024 | V | MCP-SQ | High; official MCP page. |
| Total trips (provisional balance) | 46,070,858 (+8.16% vs 2023; +13.37% vs pre-pandemic) | trips | 2024 | V (press repost) | Pamplona Actual, 2025-01-10, https://pamplonaactual.com/pamplona-actual-barrios/323592/46-millones-de-viajes-en-villavesa-en-2024-la-mayor-cifra-de-su-historia/ | High (provisional; final is 46,055,590). |
| Day lines / night lines | 44,936,495 (97.54%) / 1,134,363 (2.46%) | trips | 2024 | V | same Pamplona Actual article | High. |
| Total trips | 42,594,429 (provisional 42,572,729 in text) | trips | 2023 | V | MCP-M23 | High. |
| Total trips | 36,230,056 | trips | 2022 | V | MCP-M23 | High. |
| Total trips | 45,797,251 (-0.59%) | trips | 2025 | S | Wikipedia table https://es.wikipedia.org/wiki/Transporte_Urbano_Comarcal_de_Pamplona ; a search summary of the provisional balance gave 45,759,260 (-0.6%) | Medium. San Fermin 2025 strike affected the year. |
| San Fermin 2024 trips | 2,016,957 | trips | 2024 | V | Pamplona Actual article above | High. |
| Pre-pandemic peak | 40,639,355 | trips | 2019 | S | Wikipedia table | Medium (consistent with press "40.6 millones"). |
| Top lines 2024 | L4 Barañáin-Villava 9,231,040; L16 Aizoáin-Noáin-Beriáin 4,241,250; L7 Villava-Txantrea-Barañáin 4,177,644; L18 Zizur Mayor-Sarriguren 3,746,654 | trips | 2024 | V | Pamplona Actual article | High. |
| Top night lines 2024 | N7 264,400; N5 182,639; N2 162,334 | trips | 2024 | V | same | High. |
| Full per-line table 2023 (all 22 day + 10 night lines) | e.g. L4 8,630,031; L7 3,972,442; L16 3,902,395; L18 3,516,383; L12 2,449,008; L11 2,349,064; L19 1,933,378; L9 1,889,493 | trips | 2023 | V | MCP-M23 | High. Useful as a per-line calibration set. |
| Trips per inhabitant | 117.88 (2022: 101.48) | trips/inh | 2023 | V | MCP-M23 | High. |
| Most-used tariff 2024 | "monedero general" 40.52% | % | 2024 | V | Pamplona Actual | High. |
| Demand matrix (OD) | not found | | | | | No public OD matrix located (consistent with CLAUDE.md). |

## 4. Average commercial speed

| Item | Value | Unit | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|---|
| Network average commercial speed | **12.70** | km/h | 2022 and 2023 | V | MCP-M23 ("Velocidad media comercial (km/h) 12,70 / 12,70") | High. CLAUDE.md "~13 km/h" is consistent. |
| Same, OMM | 12.7 | km/h | 2022 | V | OMM Table 20 (C. de Pamplona, footnote: total TUC) | High. |
| Trend | 13.32 (2015) to 12.67 (about 2021/22), -4.9% | km/h | 2015-2021 | V | XPLAN section 3.5.3 | High. Definition in XPLAN: useful bus-km inside line routes / useful bus-hours inside line routes. |
| Spanish urban range | about 12 to 17 | km/h | 2022 | V | OMM, text around Table 20 | High. |
| Press "12.7 km/h, president says speed is very low" | 12.7 | km/h | 2024 | S | search summary of Noticias de Navarra Aug 2024 | Low (same number as above). |
| Barcelona TMB for comparison | 12.08 | km/h | 2017 | V | https://noticies.tmb.cat/transport/mesures-afavorir-velocitat-regularitat-autobusos | High for the figure; different city, old. |

## 5. Operating cost, revenue, subsidy

| Item | Value | Unit | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|---|
| **Contract unit price per bus-hour (PH)** | **43.1493** (2021 actual: 38.4259; 2009: 31.8083) | EUR/useful bus-hour | 2023 estimate | V | XPLAN section 5.2.1 (old concession, tariff `CO = PH*H + PK*K`, indexed to CPI and fuel) | High (plan estimate of the indexed contractual price). |
| **Contract unit price per bus-km (PK)** | **1.2518** (2021 actual: 0.9320; 2009: 0.7367) | EUR/useful bus-km | 2023 estimate | V | XPLAN section 5.2.1 | High. |
| Planned operating cost 2023 | 37,734,665.68 (km part 10,147,283.49 + hour part 27,669,838.57 - 82,456.38 deduction) | EUR | 2023 plan | V | XPLAN | High. |
| Planned capital compensation 2023 | 4,970,514.90 (fleet 4,372,147.90 + other 598,367.00) | EUR | 2023 plan | V | XPLAN section 5.2.2 | High. |
| Planned cost of execution 2023 | 42,705,180.58 | EUR | 2023 plan | V | XPLAN section 5.2.3 | High. |
| Gross cost of concession 2023 | 42,937,425.01 (incl. 232,244.43 incentives) | EUR | 2023 plan | V | XPLAN | High. |
| Total plan cost incl. MCP own costs | 45,847,562.69 (MCP other costs 2,910,137.68) | EUR | 2023 plan | V | XPLAN section 6.2 | High. |
| Planned fare revenue / coverage | 18,469,863.30 on 37,125,000 trips; fare coverage 40.29% (legal cap 50%) | EUR; % | 2023 plan | V | XPLAN section 6.2 | High (plan; outturn lower, see below). |
| Operating cost (ATP data) | 34.4 (2022); 34.7 (2023) | M EUR | 2022, 2023 | V | OMM Table 69 (source ATP), "C. Pamplona" row | Medium-High; scope may exclude MCP own costs and some incentives. |
| Fare revenue, subsidy (OMM 2022) | fares 15.65; subsidy 22.33; other 0.42; total revenue 38.40; operating cost 34.41; fare coverage 45.47%; subsidy share of cost 64.91% | M EUR | 2022 | V | OMM Table 45, "C. de Pamplona" row | Medium-High. Footnote 4 in OMM: additional investment cost (amortisation + financing) 4.07 M EUR in 2022. |
| Fare revenue series | 2019: 19.1; 2022: 17.2; 2023: 11.6 | M EUR | 2019-2023 | V | OMM Table 67 | Medium. Inconsistent with Table 45 (15.65 for 2022) and with the press figure for 2024 below; probably a different definition (net of VAT / accrual). Use with caution. |
| Net fare revenue 2024 | 13,603,415.78 (+17.87% vs 2023; -28.65% vs 2019; "pending adjustment for accruals") | EUR | 2024 | V | Pamplona Actual 2025-01-10 | High (provisional). Fares cover "slightly over 30%" of service cost per the same article, after the 50% fare discount for regular users. |
| Implied 2024 total cost (from 30% statement) | roughly 45 M EUR | EUR | 2024 | D | 13.60 / 0.30 = 45.3 M | Low; "algo mas del 30%" is approximate, so this is an upper bound. |
| Government of Navarra subsidy 2025 | 14,533,513.40 = 65% of a 22,359,251.40 deficit; remaining 35% paid by the municipalities | EUR | 2025 | S | Search summary of Noticias de Navarra 2025-05-14 and navarra.es press release, https://www.navarra.es/es/-/nota-prensa/el-gobierno-autoriza-una-subvencion-de-14-5-millones-a-la-mancomunidad-de-la-comarca-de-pamplona-para-financiar-el-transporte-urbano-comarcal | Medium; the 65/35 split is also verbatim in XPLAN (35% MCP, Ley Foral 11/2014). Could not open the press release. |
| Subsidy 2026 | 16,794,169.40 | EUR | 2026 | S | search summary, Noticias de Navarra 2026-05-27 | Low-Medium. |
| Financing rule | Navarra government funds 65% of the operating deficit; MCP / municipalities 35% | % | law | V | XPLAN (Ley Foral 11/2014; Ley Foral 8/1998 art. 6 bis); also Wikipedia | High. |
| New contract (2024-2033) tender price | 526,366,748.84 excl. VAT for 10 years; estimated value incl. options 631,640,098.61; investments 127.5 M EUR (incl. 133 buses and about 34 M EUR for depots/Agustinos) | EUR | tender 2023 | V | MCP-M23 (631.64 M) ; autobusesyautocares.com (526.4 M, 127.5 M) ; TED notices | High for totals. |
| Implied new-contract annual price | 52.64 M EUR/year (526.37 / 10) | EUR/yr | 2024+ | D | consistent with a Noticias de Navarra headline "Las villavesas van a costar 52,6 millones" (headline only, article not opened) | Medium. Includes capital for 133 new buses and depots and about 30% more service; not comparable with the 34.7 M EUR 2023 operating cost. |
| New contract unit prices (PH, PK) | **not found** | | | | | The winning bid applied a weighted discount reported by press at about 14% off the tender price (search summary, unverified, Low); contract annexes are on https://hacienda.navarra.es/sicpportal/ but I could not open them. |
| Awarded contract value (TED) | 460,887,351.27 | EUR | 2023 | S | search summary of TED award notice, https://ted.europa.eu/es/notice/777072-2023/pdf | Low-Medium; notice not opened. |
| Cost of extra frequencies 2026 | about 1 M EUR/year for 8 lines | EUR/yr | 2026 | S | search summary Noticias de Navarra 2025-12-02 | Low. |
| Energy use | 6.19 kWh/km (2023), 1.16 kWh/trip | | 2023 | V | MCP-M23 | High. |
| Diesel use pre-transition | about 4.5 million litres/yr | L | 2021 | V | XPLAN section 3.7 | High. |

## 6. Bus purchase cost and depreciation

| Item | Value | Unit | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|---|
| 6 articulated 18 m CNG (renewable gas) buses, Pamplona | 2,670,000 total, so 445,000 each | EUR (excl. VAT presumably) | 2023 | V + D | MCP-M23 (total); each = 2.67 M / 6 | High for total; VAT status not stated. XPLAN plans the same batch at 2.7 M EUR (450,000 each). |
| 10 electric BEV rigid 12 m buses (Irizar ie tram), Pamplona | 4.98 M planned (498,000 each); actual unit 493,020, of which 200,000 subsidised by MITMA | EUR | 2023 plan / actual | V + D | XPLAN section 3.8 ; MCP-M23 ("La inversion en el autobus electrico fue de 493.020,00 euros") | High. 12 m length confirmed by manufacturer news (Irizar e-mobility, Sustainable Bus). |
| Charging infrastructure for the first BEV batch | 916,327.39 depot charging (90% MITMA subsidy); planned 1,011,755 for 2,400 kW connection | EUR | 2023 | V | MCP-M23; XPLAN | High. |
| 2024 renewal plan | 10 BEV (4.98 M), 4 rigid CNG + 2 articulated CNG (2.34 M) | EUR | 2024 plan | V | XPLAN section 3.8 | High. |
| Implied rigid CNG 12 m price | about 360,000 each | EUR | 2024 plan | D | (2.34 M - 2 x 450,000) / 4 = 360,000; assumes the articulated price of 450,000 | Low-Medium; derived with an assumption. |
| 13 CNG buses (6 rigid + 7 articulated) | 4,509,259 excl. VAT | EUR | 2022 | V | OMM footnote 3 to the investment table (Pamplona) | High for total; mix average 347 k EUR/bus. |
| Gas filling station (gasinera) | 1,191,408.10 | EUR | 2022 | V | OMM same footnote | High. |
| 16 gas-electric hybrid buses | 7,000,000 total, so about 437,500 each | EUR | 2026 | S + D | Noticias de Navarra 2026-07-01 (search snippet "La inversion ha sido de siete millones de euros"); body type (rigid/articulated) not verified | Low-Medium. |
| Madrid EMT, 12 m BEV, max unit price in tender | 550,000 per unit (tender 90 buses, 82.5 M EUR excl. VAT, deliveries 2026-27) | EUR | 2025 | S | search summary of TED notice 809938-2025, https://ted.europa.eu/es/notice/809938-2025/pdf | Medium. |
| Madrid EMT 2022 award, 150 standard BEV | about 81 M EUR excl. VAT, so about 540,000 each | EUR | 2022 | S + D | https://www.hibridosyelectricos.com/autobuses/ayuntamiento-madrid-compra-150-autobuses-electrico-82-millones-euros_57960_102.html | Medium; average computed by me. |
| Malaga EMT, 12 m diesel-electric hybrid, max tender price | 460,000 excl. VAT; initial order 54 + 20 option; estimated value 37.44 M EUR; useful life at least 15 years | EUR | 2026 | V | El Espanol, https://www.elespanol.com/malaga/malaga-ciudad/20260624/malaga-prepara-mayores-renovaciones-flota-nuevos-autobuses-hibridos-millones/1003744298051_0.html | High (maximum tender price, not award). |
| TMB Barcelona, 18 m BEV night-charging | 19 units, tender budget 18,392,000 incl. VAT, so about 968,000 incl. VAT, or about 800,000 excl. VAT each | EUR | 2025 | V + D | https://noticies.tmb.cat/sala-de-premsa/tmb-adquirira-19-autobusos-electrics-seguir-augmentant-seva-flota-de-zero-emissions | Medium; budget is a ceiling and may include chargers/extras. The 18 m BEV price in Pamplona is not published (no 18 m BEV in the fleet). |
| Depreciation period used in the TUC contract | **10 years** for buses (linear, historical cost); 10 years for ticketing/AVL systems; 30 years for buildings; financing at 1-year EURIBOR + 0.25% (2.45% assumed for 2023) on net book value | years; % | 2023 | V | XPLAN section 5.2.2 | High. This is the official capital-recovery rule for TUC. |
| Typical useful life stated in Spanish tender | at least 15 years | years | 2026 | V | Malaga (above) | High for that tender. |
| Annual depreciation + financing of the existing fleet | 4,022,046.90 for "flota existente" (3,571,394.00 + 450,652.90) | EUR/yr | 2023 plan | V | XPLAN | High. |

## 7. Network size

| Item | Value | Unit | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|---|
| Lines | 24 day + 10 night (2023). After the Sept 2024 redesign: 16 night lines (N1-N16) plus 6 special/event lines (R1-R5, F) | lines | 2023 / 2024 | V (2023), S (2024) | MCP-M23; Pamplona Actual (six new night lines N11-N16 in Sept 2024); Wikipedia | High (2023), Medium (2024). Night network was redesigned again from 2026-10-08 per MCP news page (headline only: "arranca el nuevo servicio nocturno"). |
| Day network length | 248.57 (2022: 246.54) | km | 2023 | V | MCP-M23 | High. |
| Night network length | 135.46 (2022: 132.77) | km | 2023 | V | MCP-M23 | High. |
| OMM network length (lines) | 379.2 km, 24 lines | km | 2022 | V | OMM network table (C. Pamplona) | High (sum of day + night, about 379.3). |
| Stops | 557 (2022: 553): 331 shelter only, 225 post only, 1 no furniture, 114 with real-time panel | stops | 2023 | V | MCP-M23 | High. (CLAUDE.md says about 563 in the GTFS, plausible for a later feed.) |
| Population served | 361,343 (2022: 357,018) | people | 2023 | V | MCP-M23 | High. |
| Service area | 9,165.46 | ha | 2023 | V | MCP-M23 | High. |
| Population within 300 m of a stop | 99.6% urban area; 94.5% metropolitan area | % | 2022 | V | OMM Table 24 "% poblacion a menos de 300 m de una parada", C. de Pamplona | High (OMM definition). |
| Service hours | Day 06:30-22:30; night 22:30-00:30 (Sun-Thu), to 04:30 (Fri), to 06:30 (Sat) | | 2023 | V | MCP-M23 | High. |
| Operator staff | about 520 employees subrogated | people | 2023 | V | Moventis, https://www.moventis.es/es/actualidad/moventis-tcc-pamplona-renueva-la-concesion-de-transporte-urbano-comarcal-para-los-proximos-10-anos | High. |
| Punctuality / schedule compliance | 91.17% punctuality; 100% trips run | % | 2023 | V | MCP-M23 | High. |

## 8. Official service-planning standards

| Item | Value | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|
| Legal planning instrument | Plan de Transporte Urbano de la Comarca de Pamplona, approved by MCP; X Plan 2023 is the latest found | 2023 | V | XPLAN; Ley Foral 8/1998 art. 6 bis | High. |
| Fare coverage ceiling | fares must cover less than 50% of service cost | 2023 | V | XPLAN section 6.2 (Ley Foral 8/1998 art. 6 bis 3.d) | High. |
| Commercial-speed objective | "alcanzar valores semejantes a los mejores resultados obtenidos en areas metropolitanas similares" (no numeric target) | 2023 | V | XPLAN section 3.5.1 | High. |
| Priority measures named in law | bus lanes, demand-actuated signal priority, in-lane stops (no bays), speed-reducer designs that do not slow buses | 2023 | V | XPLAN section 3.5.1 and 3.5.4 | High. |
| Proposed speed package | 9 bus-taxi lanes, 19 junction-access priorities, 7 signal priorities, 15 green-wave stretches, 4 stop relocations, 39 boarding platforms; budget 972,317.61 EUR incl. VAT | 2023 | V | XPLAN section 3.5.4 | High. About 1 M EUR for the whole package. |
| Target headways, minimum frequency | **not found as a formal standard.** Observed: L4 runs every 6 min on weekdays (Wikipedia, S); a trunk line interval of 12 min is mentioned for one line in XPLAN; a 2015 study proposed 8 min trunk frequency (search summary, S) | | | XPLAN line ~2091; | Low. Searched: XPLAN full text (frecuencia, intervalo, minutos), MCP, infotuc, press. No numeric minimum-headway policy found. |
| Layover / recovery time practice | **not found.** One indirect datum: line 18 cycle time raised from 100 to 110 min in 2026 to add reliability (search summary of Noticias de Navarra 2025-12-02, S) | 2026 | S | | Low. Searched XPLAN (regulacion, recuperacion, ciclo), OMM, Spanish literature. |
| Stop spacing guidance | **not found** for Pamplona. | | | | Searched XPLAN, MCP-M23, OMM (grep "distancia entre paradas"). |
| Walking-distance coverage standard | No Pamplona standard found; OMM uses a 300 m stop-catchment indicator (see section 7: 99.6% / 94.5%) | 2022 | V | OMM Table 24 | High for the indicator definition, none for a Pamplona policy target. |
| New-contract promise | about 30% more service over 10 years; coverage extended by more than 30%; 4% extension of lines and frequencies already in 2024 | 2023 | V (trade press), S | autobusesyautocares.com (30% coverage); Wikipedia / Cadena SER (30% more service, S) | Medium. |

## 9. Spanish and international practice values (dwell time, stop removal, priority)

I did not find Spanish-specific measured dwell time per stop. International references are listed instead; flag them as such.

| Item | Value | Unit | Year | Type | Source / URL | Confidence / note |
|---|---|---|---|---|---|---|
| Door open/close time | 5 | s per stop | 2013 | V | TCRP Report 165 (TCQSM 3rd ed.), chapter 3, note to the stop-spacing exhibit: "10-s passenger service time and 5-s door opening and closing time" giving "15-s dwell at 8 stops/mi"; https://onlinepubs.trb.org/onlinepubs/tcrp/tcrp_rpt_165ch-03.pdf (page 3-43) | High for being the TCQSM assumption; US context. |
| Dwell time at stops, assumed | 15 s (8 stops/mi), 25 s (4 stops/mi), 30 s base case for capacity | s | 2013 | V | same chapter | High for the assumptions; they are model inputs, not measurements. |
| Boarding time per passenger | smart card about 2.7 s; cash or other media about 4.6 s | s/boarding | recent TCRP digest | S | search summary of TCRP material | Low-Medium; source not opened. |
| Slow-down + stop + re-accelerate per stop (without passenger activity beyond boarding) | about 20 | s | 2015 | S | nMotion stop consolidation memo, https://www.nmotion.info/wp-content/uploads/2015/09/nMotion-Stop-Consolidation-150902.pdf | Low-Medium; advocacy/agency memo, US. |
| Time saved per stop removed | 12 to 24 | s | various | S | worksinprogress.co "The United States needs fewer bus stops" https://worksinprogress.co/issue/the-united-states-needs-fewer-bus-stops/ ; TransLink Vancouver 12 to 15 s; NACTO Transit Street Design Guide "15 seconds or more" https://nacto.org/publication/transit-street-design-guide/transit-system-strategies/network-strategies/from-stops-to-stations ; TriMet Portland uses about 45 s | Low-Medium. All US/Canada, none opened by me (NACTO returned 403). Use 15 to 20 s as the central range, 45 s as the upper bound. |
| Measured effect of stop consolidation | San Francisco: +4.4 to 14.6% speed when stop density went from 5.9 to 2.5 stops/mi; Portland: 6-8% wider stop spacing gave -5.7% travel time; McGill study: coverage loss about 1% | % | 2010s | S | same search results | Low-Medium. |
| Transit signal priority (TSP) travel-time savings | 2 to 18% (typical 8 to 12%); individual sites 0 to 38% (Minneapolis), 6.1% (Sapporo) | % | 2007 | S | ITS knowledge resources citing TCRP Synthesis 83 / TCRP Report 118, https://www.itskrs.its.dot.gov/2009-b00613 (403 on fetch) | Medium (consistent across several summaries). |
| TSP, Spanish estimates | about +11% bus speed expected from signal priority (Pamplona TCC study; San Sebastian 14-km/h baseline) | % | ~2013-2015 | S | search summary of Diario de Navarra dossier (infotuc.es "Mando a distancia" 2013) | Low: project estimate, not a measurement; source PDF no longer online. |
| Bus lane effect (Spain, measured) | Removing a bus lane in A Coruna raised mean travel time by 14% and its coefficient of variation by 46% | % | 2021 | V | Vazquez Valera, Orro Arcay, Novales Ordax et al., CIT 2021 Burgos, https://riubu.ubu.es/handle/10259/7041 (the 14% figure verified on the repository page; the 46% from the search summary) | High (14%), Medium (46%). Lane in place 2008-2011. |
| BRT (full package) | running time reductions 38 to 69% | % | 2007 | S | TCRP Report 118 via ITS summary | Low for our use; full BRT, not just lanes. |

---

## Suggested cost-model parameters

All inputs below are from tables above; "V" values are quoted, everything else is arithmetic.

### A. `eur_per_bus_hour` and `eur_per_km` (operating cost, two-part tariff)

The old concession (2009-2023) paid the operator `CO = PH * H + PK * K` (XPLAN 5.2.1). The latest indexed prices found are, for 2023 (estimated):

- `PH = 43.1493 EUR / useful bus-hour` (V)
- `PK = 1.2518 EUR / useful bus-km` (V)

Check against actuals for 2023 (MCP-M23: 624,817 h, 7,985,316 km):

- Hours part: 624,817 x 43.1493 = 26.96 M EUR
- Km part: 7,985,316 x 1.2518 = 10.00 M EUR
- Total: 36.96 M EUR. Cross-check: OMM reports 34.7 M EUR operating cost for 2023 (about 6% lower; difference may be CPI/fuel indexation vs estimate, deductions, or scope), and XPLAN plans 37.73 M EUR for 8.11 M km and 641k h.

Recommended parameters (2023 euros, operating cost only, excluding capital, MCP overheads, VAT):

| Parameter | Value | How obtained |
|---|---|---|
| `eur_per_bus_hour` | **43.15** | XPLAN PH 2023 (V) |
| `eur_per_km` | **1.25** | XPLAN PK 2023 (V) |

Blended equivalents, useful for a one-parameter model:

- Per bus-hour including the km component: 36.96 M / 624,817 = **59.2 EUR/h** (D); using the XPLAN plan: 37,734,666 / 641,258 = 58.84 EUR/h (D); using OMM actual cost: 34.7 M / 624,817 = 55.5 EUR/h (D).
- Per km including the hour component: 34.7 M / 7,985,316 = **4.35 EUR/km** (D, OMM basis); 36.96 M / 7,985,316 = 4.63 EUR/km (D, contract-price basis).
- Do NOT add the 43.15 and 1.25 together with these blended figures; use either the two-part tariff or one blended number.

Caveats: (1) The new contract (from 2024-01-01) has different unit prices, which I could not find; apply the roughly 6-8% inflation since 2023 as a sensitivity if you need 2026 euros, but that is my assumption, not a sourced figure. (2) The tender's 52.64 M EUR/yr (D) is not an operating-cost parameter because it includes capital recovery for 133 new buses and depots and about 30% more service. (3) Marginal cost of one extra bus-hour in practice also moves km (about 12.8 km per bus-hour), so a marginal service hour costs about `43.15 + 12.8 x 1.25 = 59.2 EUR` (D), which equals the blended figure above.

### B. `eur_per_bus_year` (annualised capital)

Two independent derivations.

**B1. Official contract capital compensation (historic cost basis).** XPLAN 2023: fleet amortisation + financing = 4,022,046.90 EUR for the existing fleet of 159 buses (MCP-M23).
- 4,022,046.90 / 159 = **25,296 EUR/bus-year** (D) (27,498 including the 2023 renewal batch: 4,372,147.90 / 159).
- Including all other investments (ticketing, AVL, gas station, chargers): 4,970,514.90 / 159 = 31,261 EUR per bus-year (D).
- Cross-check with OMM: amortisation + financing in 2022 = 4.07 M EUR (V), i.e. 25.6 k EUR/bus-year on 159 buses (D). Consistent.

**B2. Replacement-cost annuity (what a new bus costs today).**
Annuity factor `a(n) = r / (1 - (1 + r)^-n)` with `r = 2.45%` (XPLAN financing rate assumption) and `n = 10` years (XPLAN buses life): a(10) = 0.11396; with `n = 15` (Malaga tender): a(15) = 0.08047.

| Bus | Purchase price (EUR, excl. VAT) | Source of price | Annualised, n = 10 | Annualised, n = 15 |
|---|---|---|---|---|
| Rigid 12 m CNG | 360,000 (D, low confidence) | XPLAN 2024 plan (derived) | 41,027 | 28,969 |
| Rigid 12 m BEV | 495,000 (493,020 actual / 498,000 plan) | MCP-M23, XPLAN (V) | 56,412 | 39,832 |
| Articulated 18 m CNG | 445,000 (445,000 actual / 450,000 plan) | MCP-M23, XPLAN (V) | 50,714 | 35,809 |
| Fleet-weighted average (93 rigid 12 m at 360,000 + 64 articulated at 445,000, minibuses ignored) | about 395,000 (= (93 x 360,000 + 64 x 445,000) / 157) | D | about 45,000 | about 31,800 |

For the cost model use the contract rule (it is how MCP actually pays capital):
- `eur_per_bus_year` (existing fleet, historic cost) = **25,300** (B1, D) for the baseline.
- `eur_per_bus_year` (additional bus bought new) = **about 45,000 to 51,000 for 10-year recovery** (B2, D): suggested 12 m = 41,000 (CNG) to 56,000 (BEV); 18 m = 51,000 (CNG). Use 10 years because that is the contractual amortisation; give a 15-year sensitivity (29,000 to 40,000).
- Because the optimiser spends a fixed budget, treat `eur_per_bus_year` for marginal buses as the replacement-cost number (B2), and use B1 only to reproduce the baseline cost.

Add-ons to keep separate: depot/charging infrastructure (gas station 1.19 M EUR; BEV charging 0.92 M EUR for the first batch, 90% subsidised), and MCP own costs (2.91 M EUR/yr in the 2023 plan, not bus-dependent).

### C. Consistency check of the full model against 2023

- Operating (two-part tariff) 36.96 M + capital 4.97 M = 41.93 M EUR, versus XPLAN planned cost of execution 42.71 M EUR (D vs V; -1.8%). Adding MCP own costs 2.91 M gives about 44.8 M, versus XPLAN total 45.85 M.
- Fare revenue 2024 13.60 M EUR; with the 2023 plan's deficit logic the public contribution is about 65% Navarra + 35% municipalities of the deficit.

### D. What I could not source (leave as explicit assumptions in the model)

- Peak vehicle requirement and layover/recovery rules (use a stated assumption, e.g. fleet 159 minus reserve; cycle time recovery of about 10% is common practice but **not sourced here**).
- Official minimum headway, stop spacing and coverage-distance policy for Pamplona.
- Spanish-measured dwell time per stop and per passenger.
- New-contract (2024+) unit prices PH and PK.
- 2024 vehicle-hours and 2024 operating cost (management report 2024 not found online).
- Price of an 18 m BEV bought by MCP (only the TMB ceiling of about 800,000 EUR excl. VAT is available, as a different operator's tender budget).
