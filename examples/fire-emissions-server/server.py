"""Fire emissions MCP server: gases a wildfire released, and whether its smoke shows in air-quality data."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, timedelta
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("fire-emissions-mcp")

PC_STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_ITEM_STATS = "https://planetarycomputer.microsoft.com/api/data/v1/item/statistics"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEOUT = 120

# ESA WorldCover 2021 class codes -> fuel type names.
WORLDCOVER_CLASSES = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse",
    70: "snow_ice",
    80: "water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}
NON_FUEL = {"built_up", "bare_sparse", "snow_ice", "water"}

# Fuel burned per hectare (tonnes of dry matter / ha) as (low, central, high).
# Approximate ranges from IPCC 2006 Guidelines, Vol. 4, Ch. 2, Table 2.4.
FUEL_CONSUMED_T_HA = {
    "tree_cover:tropical": (50.0, 84.0, 120.0),
    "tree_cover:temperate": (15.0, 30.0, 50.0),
    "tree_cover:boreal": (20.0, 41.0, 60.0),
    "shrubland": (10.0, 20.0, 27.0),
    "grassland": (2.0, 4.1, 10.0),
    "cropland": (3.0, 5.0, 10.0),
    "herbaceous_wetland": (3.0, 5.0, 10.0),
    "mangroves": (50.0, 84.0, 120.0),
    "moss_lichen": (1.0, 2.0, 4.0),
}

# Emission factors in g of gas per kg of dry matter burned.
# IPCC 2006 Guidelines, Vol. 4, Table 2.5 (Andreae and Merlet 2001); PM2.5 from Andreae and Merlet 2001.
EMISSION_FACTORS_G_KG = {
    "tropical_forest": {"CO2": 1580, "CO": 104, "CH4": 6.8, "N2O": 0.20, "PM2_5": 9.1},
    "extratropical_forest": {"CO2": 1569, "CO": 107, "CH4": 4.7, "N2O": 0.26, "PM2_5": 13.0},
    "savanna_grassland": {"CO2": 1613, "CO": 65, "CH4": 2.3, "N2O": 0.21, "PM2_5": 5.4},
    "agricultural_residues": {"CO2": 1515, "CO": 92, "CH4": 2.7, "N2O": 0.07, "PM2_5": 3.9},
}

# 100-year global warming potentials, IPCC AR6 (non-fossil CH4).
GWP100 = {"CO2": 1.0, "CH4": 27.0, "N2O": 273.0}
# Tailpipe CO2 of a typical passenger car per year (US EPA).
CAR_T_CO2_PER_YEAR = 4.6


def _tool_error(message: str, **extra: Any) -> str:
    return json.dumps({"error": message, **extra})


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    """Parse "west,south,east,north" and check that it is a valid lon/lat box."""
    try:
        west, south, east, north = (float(v) for v in bbox.split(","))
    except (AttributeError, ValueError):
        raise ValueError(f"bbox must be 'west,south,east,north' in degrees, got {bbox!r}.") from None
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError(f"bbox {bbox!r} is not a valid west,south,east,north box.")
    return west, south, east, north


def _parse_date(value: str) -> date:
    """Accept "YYYY-MM-DD" or an EFFIS firedate such as "2021-08-03 11:27:23.57"."""
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise ValueError(f"date must start with YYYY-MM-DD, got {value!r}.") from None


def _box_area_ha(west: float, south: float, east: float, north: float) -> float:
    """Area of a lon/lat box on a sphere, in hectares."""
    r_km = 6371.0
    area_km2 = (r_km**2) * math.radians(east - west) * (math.sin(math.radians(north)) - math.sin(math.radians(south)))
    return abs(area_km2) * 100.0


def _biome(lat: float) -> str:
    if abs(lat) < 23.5:
        return "tropical"
    if abs(lat) > 50.0:
        return "boreal"
    return "temperate"


def _worldcover_year(fire_date: str | None) -> int:
    """WorldCover exists for 2020 and 2021 only. Use the map from before the fire when there is one."""
    if fire_date and _parse_date(fire_date).year <= 2021:
        return 2020
    return 2021


async def _landcover_hectares(west: float, south: float, east: float, north: float,
                              year: int = 2021) -> dict[str, float]:
    """Hectares of each WorldCover class (2020 or 2021 map) inside the box, summed over the tiles it touches."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            PC_STAC_SEARCH,
            json={"collections": ["esa-worldcover"], "bbox": [west, south, east, north], "limit": 50},
        )
        resp.raise_for_status()
        items = [f for f in resp.json().get("features", []) if f"_{year}_" in f["id"]]
        if not items:
            raise ValueError(f"No ESA WorldCover {year} tile covers this bbox.")

        hectares: dict[str, float] = {}
        for item in items:
            # Clip the box to this tile so each piece is counted once.
            iw, is_, ie, in_ = item["bbox"]
            pw, ps, pe, pn = max(west, iw), max(south, is_), min(east, ie), min(north, in_)
            if pw >= pe or ps >= pn:
                continue
            piece = {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[[pw, ps], [pe, ps], [pe, pn], [pw, pn], [pw, ps]]]},
            }
            # max_size downsamples on the server: class fractions stay the same, and large boxes do not time out.
            resp = await client.post(
                PC_ITEM_STATS,
                params={"collection": "esa-worldcover", "item": item["id"], "assets": "map",
                        "categorical": "true", "max_size": 1024},
                json=piece,
            )
            resp.raise_for_status()
            stats = next(iter(resp.json()["properties"]["statistics"].values()))
            counts, values = stats["histogram"]
            total = sum(counts)
            if not total:
                continue
            piece_ha = _box_area_ha(pw, ps, pe, pn) * stats.get("valid_percent", 100.0) / 100.0
            for count, code in zip(counts, values, strict=True):
                name = WORLDCOVER_CLASSES.get(int(code), f"class_{int(code)}")
                hectares[name] = hectares.get(name, 0.0) + piece_ha * count / total
    return hectares


def _fuel_shares(hectares: dict[str, float]) -> dict[str, float]:
    """Percent of the vegetated (burnable) area in each fuel type."""
    fuel = {k: v for k, v in hectares.items() if k not in NON_FUEL and v > 0}
    total = sum(fuel.values())
    if not total:
        return {}
    shares = {k: round(100.0 * v / total, 1) for k, v in sorted(fuel.items(), key=lambda kv: -kv[1])}
    return {k: v for k, v in shares.items() if v > 0}


def _parse_month(value: str) -> tuple[date, date]:
    """Accept "YYYY-MM" (or a full date) and return the first and last day of that month."""
    try:
        first = date.fromisoformat(str(value).strip()[:7] + "-01")
    except ValueError:
        raise ValueError(f"month must be YYYY-MM, got {value!r}.") from None
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, next_month - timedelta(days=1)


mcp = FastMCP("fire-emissions", host="0.0.0.0", port=8000, stateless_http=True)


@mcp.tool()
async def detect_burned_area(bbox: str, month: str) -> str:
    """
    Detect burned area anywhere in the world from satellite data, for one month.

    Use this when get_effis_burnt_areas returns no fires: outside Europe, or a fire
    EFFIS has not mapped. Uses the NASA MODIS Burned Area product (MCD64A1, 500 m,
    monthly, global) on Microsoft Planetary Computer; pixels are counted on the server.
    Data appear about 1-2 months after the end of the month. Fires smaller than about
    25 ha are usually missed. All fires inside the bbox are counted together.

    Args:
        bbox: Bounding box "west,south,east,north" in degrees (lon/lat) around the fire.
        month: Month to check, "YYYY-MM" (e.g. "2023-06").

    Returns:
        JSON with burned_area_ha, the burned percent of the box, the first, last and
        peak burn dates, and the bbox. Pass burned_area_ha, bbox and first_burn_date to
        get_burn_fuel_types, estimate_fire_emissions and get_smoke_signal.
    """
    try:
        west, south, east, north = _parse_bbox(bbox)
        first_day, last_day = _parse_month(month)
    except ValueError as exc:
        return _tool_error(str(exc))
    logger.info("MODIS burned area for bbox %s, %s", bbox, first_day.strftime("%Y-%m"))

    box = {
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north],
                                                          [west, north], [west, south]]]},
    }
    # Burn_Date values: day of year (1-366) = burned, 0 = not burned, -1 = unmapped, -2 = water.
    day_counts: dict[int, float] = {}
    valid = 0.0
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(PC_STAC_SEARCH, json={
                "collections": ["modis-64A1-061"],
                "bbox": [west, south, east, north],
                "datetime": f"{first_day.isoformat()}T00:00:00Z/{last_day.isoformat()}T23:59:59Z",
                "limit": 20,
            })
            resp.raise_for_status()
            items = resp.json().get("features", [])
            if not items:
                return _tool_error(
                    f"No MODIS burned-area data for {first_day:%Y-%m} in this bbox yet. "
                    "The product is published about 1-2 months after the end of the month.",
                    bbox=bbox, month=f"{first_day:%Y-%m}",
                )
            # Send the whole box to every tile: pixels outside a tile are masked, so each pixel is counted
            # once, and the same box and max_size give every tile the same pixel size.
            skipped = []
            for item in items:
                resp = await client.post(
                    PC_ITEM_STATS,
                    params={"collection": "modis-64A1-061", "item": item["id"], "assets": "Burn_Date",
                            "categorical": "true", "max_size": 1024},
                    json=box,
                )
                # MODIS tiles are curved (sinusoidal): a tile can be listed by the search although its data
                # does not reach the box, and the statistics call then fails. Skip it and keep the others.
                if resp.status_code >= 500:
                    skipped.append(item["id"])
                    continue
                resp.raise_for_status()
                stats = next(iter(resp.json()["properties"]["statistics"].values()))
                counts, values = stats["histogram"]
                for count, value in zip(counts, values, strict=True):
                    valid += count
                    if value > 0:
                        day_counts[int(value)] = day_counts.get(int(value), 0.0) + count
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return _tool_error(f"MODIS burned-area request failed: {exc}", bbox=bbox)

    if not valid:
        return _tool_error("MODIS has no valid pixels in this bbox for that month.", bbox=bbox,
                           tiles_failed=skipped)

    burned_fraction = sum(day_counts.values()) / valid
    result: dict[str, Any] = {
        "bbox": bbox,
        "month": f"{first_day:%Y-%m}",
        "burned_area_ha": float(f"{burned_fraction * _box_area_ha(west, south, east, north):.3g}"),
        "burned_pct_of_box": round(100 * burned_fraction, 2),
        "source": "NASA MODIS Burned Area MCD64A1 v061 (500 m), Microsoft Planetary Computer",
        "note": "Approximate: 500 m pixels, all fires in the box together, fires under about 25 ha missed.",
    }
    if skipped:
        result["tiles_skipped"] = skipped
    if day_counts:
        def to_date(day_of_year: int) -> str:
            return (date(first_day.year, 1, 1) + timedelta(days=day_of_year - 1)).isoformat()

        result["first_burn_date"] = to_date(min(day_counts))
        result["last_burn_date"] = to_date(max(day_counts))
        result["peak_burn_date"] = to_date(max(day_counts, key=day_counts.get))
    else:
        result["message"] = "No burned pixels detected in this bbox for that month."
    return json.dumps(result)


@mcp.tool()
async def get_burn_fuel_types(bbox: str, fire_date: str | None = None) -> str:
    """
    Break down the land cover (fuel types) inside a burnt-area bounding box.

    Uses ESA WorldCover (10 m) on Microsoft Planetary Computer. Pixels are counted on
    the server, so nothing is downloaded. Pass the "bbox" of a fire returned by
    get_effis_burnt_areas (use buffer_km=0 there so the box hugs the burn).
    WorldCover exists for 2020 and 2021 only: give fire_date so the tool uses the map
    from before the fire (2020 for fires up to 2021, otherwise 2021).

    Args:
        bbox: Bounding box "west,south,east,north" in degrees (lon/lat).
        fire_date: Fire start date "YYYY-MM-DD" (an EFFIS "firedate" also works).
                   Optional; without it the 2021 map is used.

    Returns:
        JSON with hectares per land-cover class in the box, the map year used, and
        "fuel_shares_pct": the percent of the vegetated area in each fuel type
        (tree_cover, shrubland, grassland, cropland, ...). Pass fuel_shares_pct to
        estimate_fire_emissions.
    """
    try:
        west, south, east, north = _parse_bbox(bbox)
        year = _worldcover_year(fire_date)
    except ValueError as exc:
        return _tool_error(str(exc))
    logger.info("Land cover %d for bbox %s", year, bbox)
    try:
        hectares = await _landcover_hectares(west, south, east, north, year)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return _tool_error(f"WorldCover statistics failed: {exc}", bbox=bbox)

    if not fire_date:
        map_choice = "2021 map (no fire_date given)."
    elif year == 2020:
        map_choice = "2020 map: the land cover before a fire in 2021 or earlier."
    else:
        map_choice = "2021 map: the newest WorldCover, from before this fire."
    return json.dumps({
        "bbox": bbox,
        "worldcover_year": year,
        "map_choice": map_choice,
        "source": f"ESA WorldCover {year} {'v100' if year == 2020 else 'v200'} (10 m), Microsoft Planetary Computer",
        "box_hectares_by_class": {k: round(v) for k, v in sorted(hectares.items(), key=lambda kv: -kv[1])},
        "fuel_shares_pct": _fuel_shares(hectares),
        "biome": _biome((south + north) / 2),
        "note": "Shares describe the whole box, not only the burnt pixels inside it.",
    })


@mcp.tool()
async def estimate_fire_emissions(
    burned_area_ha: float,
    bbox: str,
    fuel_shares_pct: dict[str, float] | None = None,
    fire_date: str | None = None,
) -> str:
    """
    Estimate the greenhouse gases and smoke released by a wildfire.

    Method (IPCC 2006 Guidelines, Vol. 4, Eq. 2.27): emissions = burned area x
    fuel burned per hectare x emission factor, for each fuel type. Gases: CO2, CO,
    CH4, N2O and PM2.5, plus CO2-equivalent (IPCC AR6 GWP100) and the number of
    passenger cars that emit the same CO2 in a year. Every value is a low / central /
    high range, because fuel per hectare varies a lot between fires.

    Args:
        burned_area_ha: Burnt area in hectares, e.g. "area_ha" from get_effis_burnt_areas.
        bbox: Bounding box "west,south,east,north" of the fire. Sets the biome
              (tropical, temperate, boreal), and the fuel types if fuel_shares_pct is not given.
        fuel_shares_pct: Optional "fuel_shares_pct" from get_burn_fuel_types, e.g.
              {"tree_cover": 60, "shrubland": 25, "grassland": 15}. If omitted, it is
              computed from the bbox.
        fire_date: Optional fire date "YYYY-MM-DD". Only used when fuel_shares_pct is
              omitted, to pick the WorldCover map from before the fire.

    Returns:
        JSON with tonnes of each gas (low, central, high), CO2-equivalent, car-years,
        the inputs used, and the sources of the factors.
    """
    try:
        west, south, east, north = _parse_bbox(bbox)
        burned_area_ha = float(burned_area_ha)
        if not burned_area_ha > 0:
            raise ValueError("burned_area_ha must be a positive number of hectares.")
        year = _worldcover_year(fire_date)
    except (TypeError, ValueError) as exc:
        return _tool_error(str(exc))

    if not fuel_shares_pct:
        try:
            fuel_shares_pct = _fuel_shares(await _landcover_hectares(west, south, east, north, year))
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return _tool_error(f"Could not get fuel types for the bbox: {exc}", bbox=bbox)

    shares = {k: float(v) for k, v in fuel_shares_pct.items() if k not in NON_FUEL and float(v) > 0}
    unknown = [k for k in shares if k not in FUEL_CONSUMED_T_HA and k != "tree_cover"]
    if unknown:
        return _tool_error(
            f"Unknown fuel types {unknown}. Use the names from get_burn_fuel_types.",
            allowed=sorted({k.split(':')[0] for k in FUEL_CONSUMED_T_HA}),
        )
    total_pct = sum(shares.values())
    if not total_pct:
        return _tool_error("fuel_shares_pct has no burnable fuel types.")

    biome = _biome((south + north) / 2)
    forest_ef = "tropical_forest" if biome == "tropical" else "extratropical_forest"
    ef_class = {
        "tree_cover": forest_ef, "mangroves": "tropical_forest", "shrubland": "savanna_grassland",
        "grassland": "savanna_grassland", "herbaceous_wetland": "savanna_grassland",
        "moss_lichen": "savanna_grassland", "cropland": "agricultural_residues",
    }

    gases = ["CO2", "CO", "CH4", "N2O", "PM2_5"]
    tonnes = {g: [0.0, 0.0, 0.0] for g in gases}
    by_fuel = {}
    for fuel, pct in shares.items():
        area = burned_area_ha * pct / total_pct
        consumed = FUEL_CONSUMED_T_HA[f"tree_cover:{biome}" if fuel == "tree_cover" else fuel]
        factors = EMISSION_FACTORS_G_KG[ef_class[fuel]]
        by_fuel[fuel] = {"area_ha": round(area), "fuel_burned_t_per_ha": consumed[1],
                         "co2_t_central": float(f"{area * consumed[1] * factors['CO2'] / 1000:.3g}")}
        for gas in gases:
            for i in range(3):
                # t dry matter x g/kg = kg of gas; / 1000 -> tonnes.
                tonnes[gas][i] += area * consumed[i] * factors[gas] / 1000.0

    co2e = [sum(tonnes[g][i] * GWP100[g] for g in GWP100) for i in range(3)]

    def sig3(value: float) -> float:
        # Three significant figures: the estimate is only good to about +/-50%.
        return float(f"{value:.3g}")

    def rng(values: list[float]) -> dict[str, float]:
        return {"low": sig3(values[0]), "central": sig3(values[1]), "high": sig3(values[2])}

    return json.dumps({
        "burned_area_ha": round(burned_area_ha),
        "biome": biome,
        "fuel_shares_pct_used": {k: round(100 * v / total_pct, 1) for k, v in shares.items()},
        "emissions_tonnes": {g: rng(v) for g, v in tonnes.items()},
        "co2_equivalent_tonnes": rng(co2e),
        "co2_equivalent_includes": ["CO2", "CH4", "N2O"],
        "car_years_equivalent": rng([v / CAR_T_CO2_PER_YEAR for v in tonnes["CO2"]]),
        "by_fuel_type": by_fuel,
        "method": "IPCC 2006 Vol. 4 Eq. 2.27: area x fuel burned (Table 2.4 ranges) x emission factor (Table 2.5).",
        "sources": [
            "IPCC 2006 Guidelines for National GHG Inventories, Vol. 4, Ch. 2",
            "Andreae and Merlet (2001), Global Biogeochemical Cycles 15(4)",
            "IPCC AR6 WG1 Table 7.15 (GWP100)",
            "US EPA: 4.6 t CO2 per typical passenger car per year",
        ],
        "caveats": "Order-of-magnitude estimate (about +/-50%). Vegetation CO2 can be re-absorbed as plants regrow.",
    })


@mcp.tool()
async def get_smoke_signal(bbox: str, fire_date: str, days_after: int = 10, baseline_days: int = 14) -> str:
    """
    Check whether a wildfire's smoke is visible in air-quality data at the fire.

    Compares carbon monoxide (CO) and fine particles (PM2.5, PM10) at the centre of
    the bbox during the fire with the days before it. Data: CAMS (Copernicus
    Atmosphere Monitoring Service) via the Open-Meteo Air Quality API, no key needed.

    Args:
        bbox: Bounding box "west,south,east,north" of the fire (e.g. from get_effis_burnt_areas).
        fire_date: Fire start date, "YYYY-MM-DD" (an EFFIS "firedate" also works).
        days_after: Days after the start date to treat as the fire period (default 10).
                    Keep the default unless the fire is known to have burned longer; a long
                    window lowers the fire-period mean (the peak is not affected). Max 30.
        baseline_days: Days before the start date used as the normal level (default 14).

    Returns:
        JSON with, for each pollutant, the baseline mean, the fire-period mean and peak,
        the peak time, and how many times above normal the peak was.
    """
    try:
        west, south, east, north = _parse_bbox(bbox)
        start = _parse_date(fire_date)
        days_after = max(1, min(int(days_after), 30))
        baseline_days = max(3, min(int(baseline_days), 60))
    except (TypeError, ValueError) as exc:
        return _tool_error(str(exc))
    lat, lon = (south + north) / 2, (west + east) / 2
    if start > date.today():
        return _tool_error(f"fire_date {start} is in the future.")

    pollutants = ["carbon_monoxide", "pm2_5", "pm10"]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(AIR_QUALITY_URL, params={
                "latitude": lat, "longitude": lon, "hourly": ",".join(pollutants),
                "start_date": (start - timedelta(days=baseline_days)).isoformat(),
                "end_date": min(start + timedelta(days=days_after), date.today()).isoformat(),
                "timezone": "UTC",
            })
            resp.raise_for_status()
            hourly = resp.json()["hourly"]
    except (httpx.HTTPError, KeyError) as exc:
        return _tool_error(f"Air-quality request failed: {exc}", lat=lat, lon=lon)

    times = hourly["time"]
    split = start.isoformat()
    result = {}
    for p in pollutants:
        before = [v for t, v in zip(times, hourly[p], strict=False) if t < split and v is not None]
        during = [(v, t) for t, v in zip(times, hourly[p], strict=False) if t >= split and v is not None]
        if not before or not during:
            result[p] = {"error": "no data for this period"}
            continue
        base = sum(before) / len(before)
        peak, peak_time = max(during)
        result[p] = {
            "unit": "ug/m3",
            "baseline_mean": round(base, 1),
            "fire_period_mean": round(sum(v for v, _ in during) / len(during), 1),
            "fire_period_peak": round(peak, 1),
            "peak_time_utc": peak_time,
            "peak_vs_baseline": round(peak / base, 1) if base else None,
        }

    return json.dumps({
        "location": {"lat": round(lat, 4), "lon": round(lon, 4)},
        "fire_period": f"{start} to {start + timedelta(days=days_after)}",
        "baseline_period": f"{start - timedelta(days=baseline_days)} to {start - timedelta(days=1)}",
        "pollutants": result,
        "source": "CAMS air-quality model via Open-Meteo Air Quality API (about 11-40 km grid)",
        "note": "Model concentrations confirm smoke near the fire; they are not an emission measurement.",
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fire emissions MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="http",
        help="http for streamable-http on 0.0.0.0:8000/mcp (default); stdio for local MCP clients",
    )
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default 8000)")
    args = parser.parse_args()
    mcp.settings.port = args.port
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
