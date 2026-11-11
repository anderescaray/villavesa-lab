# Data

Every number in villavesa-lab comes from a public source listed here. Raw
downloads land in `data/raw/` (git-ignored, except the GTFS zip) and are
reproducible with `make data` (`uv run --group data python scripts/build_data.py`,
`--force` to re-download, `--skip-download` to rebuild offline from the cache).
The compact processed bundle in `data/processed/` is committed (decision D-004)
and its provenance (URLs, licences, retrieval dates, sha256 of every raw input,
row counts, output checksums) is in `data/processed/manifest.json`.

The pipeline code is in `engine/src/vlab/data/pipeline/` (one module per step),
the validated loaders in `engine/src/vlab/data/loaders.py`
(`from vlab.data import load_zones, load_sections, load_pois, load_walk_graph_arrays,
load_study_area, load_zone_sections, load_manifest`). The data root defaults to
`<repo>/data` and can be moved with `VLAB_DATA_DIR`. Loaders raise
`DataSchemaError` naming the file and the violated rule.

## Final bundle (build of 2026-11-10)

| Item | Value |
| --- | --- |
| Study area | convex hull of the 563 GTFS stops + 1.5 km, 158.8 km² |
| Census sections intersecting it | 239 (20 municipalities), 375,254 residents |
| Residents inside the study area | 365,400 |
| Zones (200 m cells kept) | 1,794 (1,309 populated) |
| Zone × section pieces | 1,900 |
| Walk graph | 67,762 nodes, 88,866 undirected edges, 2,659 km, max edge 60 m |
| POIs | hospital 3 · health_centre 35 · university 4 · industrial_estate 53 · city_centre 1 · secondary_school 48 · supermarket 105 |
| Drive graph (buses) | 21,228 nodes, 35,430 directed edges (1,520 km of directed lanes), max edge 60 m, one strongly connected component |
| Drive graph vs GTFS | 99.6% of stops within 50 m of a node (median 12.3 m, p95 24.2 m, max 96.3 m); 99.3% of 35,062 shape vertices within 15 m of an edge |
| Sections with income | 239 / 239 (ADRH 2024) |
| Bundle size | 2.3 MB |

Residents inside the study area by municipality (top 12, from
`sections.population_in_study_area`): Pamplona/Iruña 206,464 · Valle de Egüés
21,741 · Burlada 20,888 · Barañáin 19,309 · Zizur Mayor 16,364 · Aranguren
12,552 · Berriozar 11,182 · Ansoáin 10,594 · Villava 9,747 · Huarte 7,866 ·
Noáin (Valle de Elorz) 7,095 · Berrioplano 6,874.

## Processed files

| File | Content |
| --- | --- |
| `study_area.geojson` | One polygon (WGS84): convex hull of GTFS stops, buffered 1.5 km in EPSG:25830. |
| `sections.parquet` | GeoParquet (EPSG:4326), one row per census section intersecting the study area: `section_id` (CUSEC), `municipality_code`, `municipality`, `population` (whole section), `population_in_study_area`, `income_per_capita`, `income_per_household` (EUR/year, nullable, float32), `income_year`, `geometry` (simplified ≤ 2 m). |
| `zones.parquet` | GeoParquet (EPSG:4326) 200 m cells aligned to multiples of 200 m in EPSG:25830: `zone_id` (dense 0..N-1, ordered south→north then west→east), `x`, `y` (cell centre, EPSG:25830), `lon`, `lat`, `population` (int), `activity_weight` (m² of non-residential floor area), `n_pois`, `section_id` / `municipality` (section contributing most residents, else largest overlap), `geometry`. Only cells intersecting the study area with population > 0, activity > 0 or a POI. |
| `zone_sections.parquet` | Crosswalk `zone_id`, `section_id`, `population`: residents each section puts in each zone (a cell can straddle sections). Sums per section equal `population_in_study_area` exactly. Added beyond the original contract to make conservation testable and to let the equity view mix incomes of straddling cells. |
| `pois.parquet` | `poi_id`, `category`, `name`, `lon`, `lat`, `weight`, `source`, `source_id`. |
| `walk_graph.npz` | `node_lon`, `node_lat` (float64), `indptr`, `indices` (int32), `length_m` (float32): symmetric CSR, one connected component. |
| `drive_graph.npz` | Directed street graph for buses, CSR by origin node: `node_lon`, `node_lat` (float64), `indptr`, `indices` (int32), `length_m`, `speed_kmh` (float32 per edge), `highway_class` (uint8 per edge, index into the string array `highway_classes`, also listed in `manifest.json` → `drive_graph.highway_classes`). Used to snap newly drawn lines to streets. |
| `manifest.json` | Sources, licences, retrieval dates, sha256, counts, parameters, drive-graph sanity checks. |

## Sources

### GTFS TUC Pamplona
- **Source**: Spain's National Access Point for multimodal transport, feed 1177
  (<https://nap.transportes.gob.es/Files/Detail/1177>). Committed as
  `data/raw/gtfs_tuc_pamplona.zip`.
- **Reference**: service 2026-11-10 → 2026-11-30.
- **Use here**: only `stops.txt` (study-area hull). Timetables are loaded by `vlab.gtfs`.

### OpenStreetMap (Navarra extract)
- **URL**: <https://download.openstreetmap.fr/extracts/europe/spain/comunidad_foral_de_navarra-latest.osm.pbf>
  (fallback <https://download.geofabrik.de/europe/spain/navarra-latest.osm.pbf>, not
  reachable from the build environment; decision D-005).
- **Licence**: ODbL 1.0, © OpenStreetMap contributors.
- **Date**: daily extract; retrieval date in the manifest.
- **Processing**: one pyosmium pass (`pipeline/osm_extract.py`) over the bounding box
  of the census sections touching the study area: highway ways, building polygons,
  land-use polygons and POI candidates.
- **Walk graph** (`pipeline/walk_graph.py`):
  - walkable: `footway, path, pedestrian, steps, residential, living_street, service,
    tertiary(_link), secondary(_link), primary(_link), unclassified, track, cycleway,
    road, bridleway, corridor, crossing, elevator`; `motorway`/`trunk` (and
    `motorroad=yes`) only with `foot=yes|designated|permissive` or a
    non-separate `sidewalk`; excluded when `foot=no`, `indoor=yes`, or
    `access=private|no` without an explicit foot permission. `busway`, `construction`,
    `proposed`, `platform` are not walkable.
  - nodes are way intersections and way ends; segments are split into equal pieces so
    no edge exceeds 60 m (edge length = true polyline length in EPSG:25830);
    segments not fully inside the study area are dropped; self-loops dropped,
    parallel edges keep the shortest; only the largest connected component is kept
    (99.1% of nodes).
- **Drive graph for buses** (`pipeline/drive_graph.py`, same OSM pass):
  - classes: `motorway, trunk, primary, secondary, tertiary, unclassified,
    residential, living_street` and their `_link` variants, `busway`,
    `bus_guideway`; `service` only with `bus` or `psv` = `yes|designated`;
    excluded when `access`, `motor_vehicle` or `vehicle` is `no|private` unless
    `bus`/`psv` = `yes|designated|permissive`; `pedestrian`/`footway` never.
  - direction: `oneway=yes|true|1` forward, `-1` backward; roundabouts
    (`junction=roundabout|circular`) and `motorway(_link)` implied one-way unless
    `oneway=no`; bus contraflow with `oneway:bus=no`, `oneway:psv=no` or
    `busway[:left|:right|:both]=opposite_lane`.
  - `speed_kmh`: `maxspeed:forward|backward` or `maxspeed` (numbers, mph, `ES:urban`
    50, `ES:zone30` 30, `ES:zone20` 20), else the legal default by class (RD 970/2020
    urban limits): primary/secondary/tertiary 50, unclassified/residential 30,
    living_street/service 20, links 40 (trunk_link 50, motorway_link 60), trunk 80,
    motorway 100, busway 50. These are speed limits, not bus running speeds.
  - same splitting/densification as the walk graph (≤ 60 m edges), segments fully
    inside the study area, shortest of parallel edges, largest strongly connected
    component (98.0% of nodes).
  - sanity vs GTFS: 99.6% of the 563 stops lie within 50 m of a node (median 12.3 m);
    the only two beyond are both "Universidad Pública de Navarra" (94–96 m), served by
    a campus road that OSM tags as `highway=service` without `bus`/`psv`. 99.3% of
    GTFS shape vertices are within 15 m of an edge.
- **Caveats**: OSM completeness varies (sidewalks are mapped as separate footways in
  much of Pamplona; elsewhere the carriageway stands in for its sidewalk). No
  slope, crossings or barriers are modelled: walking speed is applied uniformly by
  the engine.

### INE census sections (seccionado 2025)
- **URL**: <https://www.ine.es/prodyser/cartografia/seccionado_2025.zip>
  (sections as of 2025-01-01, ETRS89 / UTM 30N).
- **Licence**: INE terms of use: free reuse citing INE as the source.
- **Why 2025**: it is the boundary set the ADRH 2024 tables are published on (the
  2024 boundary file lacks section `3120108011`, which carries 2024 income data,
  while it still has `3120105008`, which has none). Join coverage is 100%.
- **Processing**: province 31, sections intersecting the study area; geometry
  simplified with a 2 m tolerance (topology preserved) for the committed file.

### Population per section: INE ADRH demographic indicators
- **URL**: <https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/31132.csv> (table 31132,
  Navarra), indicator "Población", period 2024.
- **Licence**: INE terms of use.
- **Why this table**: it is INE's official section-level resident population and it
  shares the section codes and reference year of the income data. INE's Padrón
  section files for recent years are not reachable as stable downloads, and
  `datos.gob.es` is blocked from the build environment.
- **Check**: Pamplona/Iruña 206,464 residents (sum of its sections).
- **Caveat**: Padrón-based residents (registered population), reference year 2024.

### Household income per section: INE ADRH
- **URL**: <https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/31124.csv> (table 31124,
  "Indicadores de renta media y mediana", Navarra).
- **Fields**: `income_per_capita` = "Renta neta media por persona",
  `income_per_household` = "Renta neta media por hogar", EUR/year, income year 2024.
- **Resolution**: full census-section resolution. Navarra (a foral territory) is
  covered by the current ADRH edition (series 2015–2024); 2024 values are present for
  all 239 sections of the study area.
- **Caveat**: net income from tax records; the ADRH suppresses sections with too few
  records (none in the study area for 2024).

### Buildings: foral cadastre of Navarra (IDENA)
- **URLs**: `CATAST_Pol_Edificacion.zip` (building volume footprints) and
  `CATAST_Txt_EdifAlturas.zip` (height label of each volume) from
  <https://filescartografia.navarra.es/2_CARTOGRAFIA_TEMATICA/2_7_CATASTRO/2_7_1_SHAPEFILE/>.
- **Licence**: CC BY 4.0, Gobierno de Navarra (Registro de la Riqueza Territorial /
  IDENA).
- **Why**: OSM in Navarra has ~27k building polygons around Pamplona but only 12% of
  the footprint carries `building:levels`; the cadastre has every volume (80k in the
  area) with its number of floors, so floor area is measured rather than assumed.
- **Processing** (`pipeline/buildings.py`): each label point is joined to the volume
  containing it (one label per volume in >98% of cases; otherwise the tallest);
  floors above ground = the Roman numeral in the `+`-separated label (`S+V+T` → 5;
  basements `S/SS/2S`, terrace `T`, porch `P`, mezzanine `E`, paving `PAV`, pools etc.
  not counted); volumes < 15 m² dropped. Floor area = footprint × floors
  (35.0 km² of floor area above ground; 11% of footprint has no floor above ground).
- **Use class** (the cadastre layer has no use attribute), first rule that applies:
  1. OSM building polygon containing the volume's representative point, by its
     `building` value (`apartments`, `house`, … → residential; `industrial`,
     `retail`, `school`, `hospital`, … → non-residential; `garage`, `shed`, `roof`, …
     → excluded) or by `amenity`/`office`/`craft` tags;
  2. OSM facility area (`amenity=hospital|university|college|school|clinic`) → non-residential;
  3. official industrial estate (IDENA `DOTACI_Pol_PolInd`) → non-residential;
  4. OSM land use (`residential` → residential; `industrial|commercial|retail` → non-residential);
  5. otherwise unknown.
  Result by floor area: residential 71.6%, non-residential 26.2%, unknown 1.7%,
  excluded 0.5%; the deciding rule was the OSM building in 79.5% of floor area,
  OSM land use 16.0%, industrial estates 3.2%, facilities 0.7%, none 0.6%.
- **Caveats**: mixed-use buildings (shops on the ground floor, homes above — typical
  of the Ensanches) count entirely as residential when OSM tags them so; use is
  inferred, not registered.

### POIs
Official registers first (Gobierno de Navarra via the IDENA WFS
`https://idena.navarra.es/ogc/wfs`, CC BY 4.0), OpenStreetMap otherwise. Only POIs
inside the study area. Rules are in `pipeline/pois.py`:

| Category | Source and rule | Weight |
| --- | --- | --- |
| `hospital` | SNS specialised-care register `DOTACI_Sym_SNSEspecial`; entries named "Hospital …"/"Clínica …", one per name; Clínica Arcángel San Miguel excluded (mental-health / long-stay, not a general hospital). Result: Hospital Universitario de Navarra, Clínica Universidad de Navarra, Hospital San Juan de Dios (Clínica Ubarmin lies outside the study area). | 1 |
| `health_centre` | SNS primary-care register `DOTACI_Sym_SNSPrimaria`: all centros de salud and consultorios (public primary care), entries at the same location merged. 26 centros de salud + 9 consultorios. | 1 |
| `university` | OSM `amenity=university` with a name, grouped by institution (name before " - "), features within 300 m merged into a campus, one point per campus at its largest feature: UPNA Arrosadía, UPNA Facultad de Ciencias de la Salud, Universidad de Navarra, UNED Pamplona. | 1 |
| `industrial_estate` | Official estates `DOTACI_Pol_PolInd`, polygons with the same name dissolved, ≥ 5 ha, point = representative point (Landaben, Agustinos/Comarca I, Mutilva, Areta, Noáin-Esquíroz, Volkswagen Navarra, …). | area m² |
| `city_centre` | OSM feature named "Plaza del Castillo". | 1 |
| `secondary_school` | Education register `DOTACI_Sym_Ctroseduca`, centres flagged `ESO` or `BACHILLER` (public IES/IESO, concertados, ikastolas, school of art). | 1 |
| `supermarket` | OSM `shop=supermarket`; duplicates merged (same brand/name within 75 m, any within 15 m; mapped areas preferred to nodes). | 1 |

Caveats: OSM supermarket coverage is good in Pamplona but not guaranteed complete;
the education register lists centres at their main address (a multi-site school is
one point); university campuses are points, not their full extent.

### Grid and dasymetric population (`pipeline/zones.py`)
- 200 m cells in EPSG:25830 aligned to multiples of 200 m (decision D-003).
- Each section's population is split over every cell it overlaps, proportionally to
  the floor area of its buildings that are **not** non-residential (residential +
  unknown), using the building's representative point. Fallbacks: all floor area
  if a section has none; the area of overlap if a section has no building. In this
  build all 239 sections used the first tier.
- Integer residents are allocated with the largest-remainder method, so every
  section total is preserved exactly (tested). The allocation runs on the whole
  section; cells not intersecting the study area are then dropped, and
  `population_in_study_area` records what remains (sections that straddle the
  boundary are the large rural ones; 9,854 residents fall outside).
- `activity_weight` = non-residential floor area (m²) per cell, a transparent proxy
  for jobs and activity. **It is not employment data**: a warehouse and an office
  of the same floor area weigh the same, and the proxy ignores teleworking and
  shift patterns.
- **Caveat**: the within-section distribution is modelled, not observed; sections
  themselves are the finest official geography.

## Not used / tried
- INE 1 km² population grid: superseded by section totals + cadastre floor area.
- `datos.gob.es` (Navarra open-data catalogue mirror): blocked (HTTP 403) from the
  build environment; the same Gobierno de Navarra datasets were taken from IDENA.
- Overpass API and Geofabrik: not reachable; the openstreetmap.fr mirror serves the
  same OSM data.
