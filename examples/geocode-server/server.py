"""Geocode MCP server — lab example (Nominatim → west,south,east,north bbox)."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("geocode-mcp")

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "geocode-mcp/0.1 (agentic-eo-hackathon)")
TIMEOUT = 60

_PORT = int(os.getenv("MCP_PORT", "8000"))
mcp = FastMCP("Geocode", host="127.0.0.1", port=_PORT, stateless_http=True)


async def _http_get(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=100, follow_redirects=True) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp


@mcp.tool()
async def geocode_local(
    place_name: str,
    buffer_km: float = 0.0,
    limit: int = 5,
) -> str:
    """Convert a place name to a bounding box.

    Geocodes a place name (city, region, country, landmark, etc.) into a
    bounding box string in "west,south,east,north" format — the same format
    accepted by get_effis_burnt_areas and other tools.

    Uses the OpenStreetMap Nominatim API (free, no API key required).

    Args:
        place_name: Name of the place to geocode (e.g. "Greece",
                    "Athens", "Evia island", "Peloponnese").
        buffer_km:  Optional buffer in km to expand the bbox (default 0).
        limit:      Maximum number of candidate results to return (default 5).

    Returns:
        JSON with the top result's bbox string (ready to pass to other tools)
        and all candidate matches.
    """
    logger.info("Geocoding place: %s", place_name)

    try:
        resp = await _http_get(
            NOMINATIM_SEARCH_URL,
            params={
                "q": place_name,
                "format": "json",
                "limit": str(limit),
                "addressdetails": "1",
            },
            headers={"User-Agent": NOMINATIM_USER_AGENT},
        )
        results = resp.json()
    except Exception as exc:
        return json.dumps({"error": f"Geocoding failed: {exc}"})

    if not results:
        return json.dumps(
            {
                "error": f"No results found for '{place_name}'.",
                "place_name": place_name,
            }
        )

    def _parse_result(r: dict) -> dict | None:
        bb = r.get("boundingbox")
        if not isinstance(bb, (list, tuple)) or len(bb) != 4:
            return None
        try:
            south, north, west, east = map(float, bb)
            lat = float(r.get("lat", 0))
            lon = float(r.get("lon", 0))
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(v) for v in (south, north, west, east, lat, lon)):
            return None

        # A degree of latitude is ~111 km. Longitude shrinks by cos(latitude).
        # https://en.wikipedia.org/wiki/Longitude#Length_of_a_degree_of_longitude
        d_lat = buffer_km / 111.0
        widest_lat = min(max(abs(south), abs(north)) + d_lat, 89.0)
        d_lon = buffer_km / (111.0 * math.cos(math.radians(widest_lat)))

        south = max(south - d_lat, -90.0)
        north = min(north + d_lat, 90.0)
        west = max(west - d_lon, -180.0)
        east = min(east + d_lon, 180.0)

        out = {
            "display_name": r.get("display_name", ""),
            "bbox": f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}",
            "bbox_array": [round(west, 4), round(south, 4), round(east, 4), round(north, 4)],
            "lat": lat,
            "lon": lon,
            "osm_type": r.get("osm_type", ""),
            "class": r.get("class", ""),
            "type": r.get("type", ""),
        }
        if east - west > 180:
            out["warning"] = (
                "Bounding box spans more than 180 degrees longitude and crosses the antimeridian. "
                "BBox is invalid."
            )
        return out

    parsed = []
    for result in results:
        if not isinstance(result, dict):
            continue
        item = _parse_result(result)
        if item is not None:
            parsed.append(item)

    if not parsed:
        return json.dumps(
            {
                "error": "Geocoding returned no usable coordinates.",
                "place_name": place_name,
            }
        )

    return json.dumps(
        {
            "place_name": place_name,
            "top_result": parsed[0],
            "all_results": parsed,
            "total_results": len(parsed),
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Geocode MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio for MCP clients (default); http for streamable-http deployment",
    )
    parser.add_argument("--port", type=int, default=_PORT, help="HTTP port (default from MCP_PORT or 8000)")
    args = parser.parse_args()
    if args.port != mcp.settings.port:
        mcp.settings.port = args.port
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
