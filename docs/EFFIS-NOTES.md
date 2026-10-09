# EFFIS and implementation notes

Companion to the local planning file `.ada/ROADMAP.md` (not tracked). Source inspection, not proof that the live EVE deployment exposes the same version. No implementation in this planning task.

## What EFFIS already does

Source: sibling `../mcp-tool-registry`, revision `69bfcde`, `servers/effis/server.py`.

| Existing component | Verified source behaviour | Implication for us |
|---|---|---|
| `get_effis_burnt_areas` (line 635) | Searches a west,south,east,north bbox, with optional date selector and buffering. Uses EFFIS layers/WFS or local shapefile paths according to the request. | Reuse discovery rather than creating another fire finder. |
| Compact fire results (around 873–932) | Records contain buffered bbox, hectares, commune, country, and `firedate`. Full geometry is written to `saved_geojson` on the server. No explicit stable feature ID/summary-to-polygon contract. | Do not treat the bbox as a perimeter or assume we can open the server's path locally. Confirm the selected polygon and its dates explicitly. |
| `compute_metrics` (line 1919) | Takes bbox and one `fire_date`. Computes pre/post spectral metrics, a dNBR burn mask, severity classes and optional recovery. Defaults include 100 m resolution and three-month windows. | The service is already more than a perimeter tool. Try its useful existing products before implementing spectral analysis. Its date model is not an event interval. |
| `_compute_severity_map` (line 1667) | Fixed dNBR classes: low, moderate-low, moderate-high, high; NoData is separate from unburned/regrowth. | These are spectral proxy classes, not validated damage or mortality for our event. We must preserve the NoData distinction. |
| Metrics result (around 2526) | `ok`, `burn_mask`, `severity_map`, `summary`, `plots`, counts of pre/post images, `saved_json`, `save_dir`; warnings/errors may also occur. | Image counts are not images. Verify displayable artifacts, coverage and warnings. Success alone does not mean every phase has usable scenes. |
| CDSE authentication | Uses client ID/secret from request headers or server environment. | Not configured locally during inspection; the lab server may differ. Do not assume either availability or failure without trying the live tool. |

### Spectral analysis products already implemented

`compute_metrics` uses Sentinel-2 L2A through Copernicus Data Space / Sentinel Hub to produce:

| Capability | What it produces |
|---|---|
| **NDVI** | Vegetation-index statistics before and after the fire |
| **NBR** | Burn-index statistics |
| **BAIS2** | Sentinel-2 burned-area-index statistics |
| **Burn mask** | Pixels identified using pre/post median NBR differences |
| **Severity map** | Colour-coded dNBR severity classes and pixel counts |
| **Regrowth** | NDVI-based Vegetation Recovery Rate, tables and plots |
| **Visualisations** | Per-date index PNGs, composite previews and time-series plots |

These are spectral-change and vegetation-response products, not live thermal measurements or confirmation of structural damage. Generated files live on the server; returned paths do not make them locally accessible.

Current notebook cell 15 asks about **Evia, Greece** with `create_agent([geocode_mcp, "effis", "serpapi"], ...)`. That is a broad briefing, not a selected fire with a confirmed perimeter/date window. Cells 18–19 are extension seams. Existing helpers live under `lib/agentic_eo/`.

### Extend EFFIS or create a sibling?

We decided on a notebook deliverable, **not** either server architecture. Working recommendation for the timed build: use EFFIS from the notebook and add direct weather/exposure calls there. No EFFIS modification is required to compose those results. Decide whether to extract an EFFIS contribution or sibling MCP tool only if there is time for the bonus PR.

## Weather: first useful result

Use the actual perimeter's centroid, calculated in a suitable local metric CRS then transformed to lon/lat. A single point is regional context, not a weather field over the whole burn.

Open-Meteo archive request:

- `latitude`, `longitude`, `start_date`, `end_date`;
- `hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation`;
- `daily=precipitation_sum`, `models=era5`, `timezone=UTC`, `wind_speed_unit=ms`.

One bounded request can include the preceding 30 days and the event window; display event-hour series separately from antecedent daily rain. Preserve null values and report missing hours/days rather than treating them as dry/calm. Use a historical event, not a forecast/reanalysis mixing pipeline.

Verified with one public parameter probe: HTTP 200, 24 hourly rows, requested ERA5, GMT/UTC, wind/gusts m/s, humidity %, precipitation mm. This was only an API contract check, not validation of the chosen event. Detailed recent-data latency and per-variable availability still depend on the provider.

Interpretation:

- Meteorological wind direction is where the wind comes **from**; any downwind arrow points 180° away. Do not arithmetically average angles across north.
- Wind is contextual evidence, not a predicted fire front or safe route.
- Rain/RH do not measure local fuel moisture or prove that the fire slowed. Avoid that causal claim.
- ERA5 is coarse regional reanalysis (roughly 25 km); do not draw local valley-wind conclusions or assume choosing a finer land model fixes wind representation.
- Credit Open-Meteo and the model; API service terms and the CC BY 4.0 data licence are separate matters.

## Exposure: minimal and honest

Overpass uses **south,west,north,east**, unlike the usual GeoJSON/EFFIS bbox order. Query building/highway ways with full geometry, validate returned geometries, then intersect with the actual fire perimeter. Compute road lengths in a local metric CRS.

For the smallest first pass, count mapped building **ways** intersecting the perimeter and report road-way length within it. This omits relation-only buildings and incomplete OSM mapping; label the coverage explicitly. `highway` includes tracks/paths, not only vehicle roads; retain its class in the display. Query failure is not zero exposure. Bbox selection is a candidate search, not a guarantee of every enclosing/crossing OSM feature.

## Imagery: only write what we cannot reuse

If new raster cells are needed, use a small, explicitly bounded real fire and one compatible pre/post Sentinel-2 pair. Prefer one provider/tile; no automatic mosaicking or catalogue abstraction for the hackathon.

- Display dates, spatial coverage and source IDs. Pre-image must precede the event; post-image must follow it, with seasonality/regrowth limitations stated.
- Validate provider-specific reflectance scaling/offsets before computing an index. Do not infer harmonization solely from acquisition date or assume a multiplicative scale cancels an additive offset.
- B08 is 10 m; B12 and SCL are 20 m. Align to a common projected grid; use nearest-neighbour for masks, appropriate continuous resampling for reflectance.
- Mask clouds, shadows, snow, invalid/saturated and missing pixels; inspect SCL handling for dark/burned surfaces. Report shared valid area over the perimeter.
- `NBR = (NIR - SWIR2) / (NIR + SWIR2)`; `dNBR = NBR_before - NBR_after`. Mask near-zero denominators. Continuous dNBR is a **spectral change proxy**, not structural damage.
- No usable image pair means no proxy result. A cached preview, empty layer or NoData pixel must not masquerade as a successful analysis.

## Small glossary

- **Perimeter:** source-provided burn footprint; keep provenance and observation/date meaning.
- **BBox:** rectangular query window, often buffered; not the footprint.
- **Exposure:** a mapped asset intersects the perimeter; not evidence of damage.
- **Severity proxy:** spectral response to change, subject to cloud, phenology and acquisition limits.
- **Inspection context:** evidence for a person to examine; no automatic emergency priorities.
- **Slope:** optional terrain context for post-fire erosion/access, not burn severity. Copernicus DEM is a surface model including vegetation/buildings.

## Sources

- [Open-Meteo archive](https://open-meteo.com/en/docs/historical-weather-api) · [licence](https://open-meteo.com/en/licence)
- [Overpass bounding boxes](https://dev.overpass-api.de/overpass-doc/en/full_data/bbox.html)
- [Planetary Computer Sentinel-2 collection](https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a) · [Copernicus DEM](https://planetarycomputer.microsoft.com/api/stac/v1/collections/cop-dem-glo-30)
- [Sentinel-2 L2A documentation](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html)
- [NPS: fire behaviour and terrain](https://home.nps.gov/articles/wildland-fire-behavior.htm) · [USGS: post-fire debris flows](https://www.usgs.gov/publications/post-wildfire-debris-flows)

Astra consultation was attempted but blocked by the advisor's image-transcript context-fit check. These notes are not advisor-reviewed.
