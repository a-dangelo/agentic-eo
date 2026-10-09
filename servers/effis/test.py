#!/usr/bin/env python3
"""
Integration test for the Fire Detection MCP Server.
Modified for the Agentic EO hackathon: weather and real-perimeter exposure checks.

Starts the server locally on HTTP, connects with an MCP client, and
exercises every tool through the protocol — exactly as a real caller would.

Three test tiers:
  1. geocode_place          — free (Nominatim), no credentials needed
  2. get_effis_burnt_areas  — free (EFFIS WFS), no credentials needed
  3. compute_metrics        — requires CDSE credentials (skipped if absent)

Credentials come from .env / env vars by default.  Override them from
the command line to test the per-request header proxy flow.

Usage:
    # Quick test (tools 1 & 2 only — no CDSE credentials needed):
    python test.py

    # Full test with CDSE (all 3 tools):
    python test.py --cdse-client-id ID --cdse-client-secret SECRET

    # Custom port:
    python test.py --port 9200

    # Offline unit tests (VRR / severity map — no server, no network):
    python test.py --unit-tests
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

SERVER_DIR = Path(__file__).resolve().parent
SERVER_PY = SERVER_DIR / "server.py"
DEFAULT_PORT = 9100
STARTUP_TIMEOUT = 15
TOOL_TIMEOUT = 180


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _print_result(result) -> dict | None:
    """Pretty-print a tool result and return the parsed JSON."""
    try:
        text = result.content[0].text
        parsed = json.loads(text)
        print(json.dumps(parsed, indent=2, default=str)[:3000])
        if len(json.dumps(parsed)) > 3000:
            print("  ... (truncated)")
        return parsed
    except (json.JSONDecodeError, IndexError, AttributeError):
        print(result.content[0].text[:3000])
        return None


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def _start_server(port: int, env_overrides: dict[str, str]) -> subprocess.Popen:
    """Launch server.py as a subprocess on the given port."""
    env = {**os.environ, **env_overrides}
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PY), "--transport", "http", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


async def _wait_for_server(url: str, timeout: float = STARTUP_TIMEOUT) -> None:
    """Poll the server until it accepts connections."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(url)
                if resp.status_code < 500:
                    return
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.3)
    raise TimeoutError(f"Server did not start within {timeout}s")


def _stop_server(proc: subprocess.Popen) -> None:
    """Gracefully stop the server subprocess."""
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


async def test_list_tools(session: ClientSession) -> list[str]:
    """List available tools and return their names."""
    _section("LIST TOOLS")
    tools_result = await session.list_tools()
    names = []
    for t in tools_result.tools:
        print(f"  - {t.name}: {t.description[:80]}")
        names.append(t.name)
    print(f"\n  Total: {len(names)} tools")

    expected = {"geocode_place", "get_effis_burnt_areas", "compute_metrics", "get_fire_weather", "get_fire_exposure", "get_community_air_quality"}
    missing = expected - set(names)
    assert not missing, f"Missing tools: {missing}"
    print("  [PASS] all expected tools registered")
    return names


async def test_geocode_place(session: ClientSession, place: str = "Sardinia") -> dict:
    """Test geocode_place — free Nominatim lookup."""
    _section(f"TEST: geocode_place({place!r})")

    t0 = time.time()
    result = await session.call_tool(
        "geocode_place",
        {"place_name": place, "buffer_km": 5.0},
    )
    elapsed = time.time() - t0
    parsed = _print_result(result)
    assert parsed is not None, "Failed to parse response"

    if "error" in parsed:
        print(f"\n  [FAIL] {parsed['error'][:200]}")
        return parsed

    top = parsed.get("top_result", {})
    assert "bbox" in top or "bbox" in parsed, "Response missing bbox"
    bbox = top.get("bbox") or parsed.get("bbox")
    print(f"\n  Elapsed: {elapsed:.1f}s")
    print(f"  bbox: {bbox}")
    print(f"  name: {top.get('display_name', '?')}")
    print("  [PASS] geocode_place returned valid bbox")
    return parsed


async def test_get_effis_burnt_areas(session: ClientSession) -> dict:
    """Test get_effis_burnt_areas — free EFFIS WFS lookup."""
    _section("TEST: get_effis_burnt_areas(date='today', Sardinia)")

    t0 = time.time()
    result = await session.call_tool(
        "get_effis_burnt_areas",
        {"bbox": "8.1,38.8,9.8,41.3", "max_features": 3, "date": "today"},
    )
    elapsed = time.time() - t0
    parsed = _print_result(result)
    assert parsed is not None, "Failed to parse response"

    if "error" in parsed:
        print(f"\n  [FAIL] {parsed['error'][:200]}")
        return parsed

    print(f"\n  Elapsed:     {elapsed:.1f}s")
    print(f"  data_source: {parsed.get('data_source', '?')}")
    print(f"  features:    {parsed.get('total_features', '?')}")
    print("  [PASS] get_effis_burnt_areas returned valid response")
    return parsed


async def test_compute_metrics(session: ClientSession) -> dict:
    """Test compute_metrics — requires CDSE credentials."""
    _section("TEST: compute_metrics (small bbox, Athens 2025-08-15)")

    t0 = time.time()
    result = await session.call_tool(
        "compute_metrics",
        {
            "bbox": "23.5,37.9,24.0,38.3",
            "fire_date": "2025-08-15",
            "months_before": 2,
            "months_after": 2,
            "metrics": ["ndvi"],
            "max_cloud_cover": 30.0,
            "resolution_m": 0,
            "width": 128,
            "height": 128,
        },
    )
    elapsed = time.time() - t0
    parsed = _print_result(result)
    assert parsed is not None, "Failed to parse response"

    if "error" in parsed:
        print(f"\n  [FAIL] compute_metrics: {parsed['error'][:200]}")
        return parsed

    summary = parsed.get("summary", {})
    print(f"\n  Elapsed:          {elapsed:.1f}s")
    print(f"  pre-fire obs:     {summary.get('pre_fire_observations', '?')}")
    print(f"  post-fire obs:    {summary.get('post_fire_observations', '?')}")
    print(f"  pre NDVI mean:    {summary.get('pre_fire_mean_ndvi', '?')}")
    print(f"  post NDVI mean:   {summary.get('post_fire_mean_ndvi', '?')}")
    print("  [PASS] compute_metrics returned valid response")
    return parsed


async def test_community_air_quality(session: ClientSession) -> None:
    """Real OSM Agia Anna point, the Evia fire date, and real CAMS/ERA5 data."""
    result = await session.call_tool("get_community_air_quality", {
        "place_name": "Αγία Άννα", "latitude": 38.8587051, "longitude": 23.3987082,
        "fire_latitude": 38.883299286859646, "fire_longitude": 23.319992618181203,
        "start_date": "2021-08-03",
    })
    data = json.loads(result.content[0].text)
    assert data.get("ok"), data
    assert data["baseline_hours"] == 168 and data["event_hours"] == 24
    assert data["baseline_end"] == "2021-08-02" and data["timezone"] == "UTC"
    for pollutant in data["pollutants"].values():
        assert pollutant["unit"] == "μg/m³"
        assert abs(pollutant["mean_change"] - (pollutant["event_mean"] - pollutant["baseline_mean"])) < 1e-9
    fraction = data["wind_context"]["aligned_fraction"]
    assert fraction is None or 0 <= fraction <= 1
    print("  [PASS] real community air-quality MCP call: units, baseline, differences and wind fraction")


async def test_get_fire_exposure(session: ClientSession, path: str, index: int) -> dict:
    """Use a real saved EFFIS perimeter and the live Overpass service."""
    _section("TEST: get_fire_exposure (real EFFIS perimeter)")
    result = await session.call_tool("get_fire_exposure", {"geojson_path": path, "feature_index": index})
    parsed = json.loads(result.content[0].text)
    assert parsed.get("ok"), parsed
    assert parsed["building_way_count"] >= 0 and parsed["road_km"] >= 0
    assert abs(sum(parsed["road_km_by_class"].values()) - parsed["road_km"]) < 1e-6
    assert Path(parsed["map_path"]).stat().st_size > 0
    assets = json.loads(Path(parsed["geojson_path"]).read_text())
    assert assets["type"] == "FeatureCollection"
    assert sum(f["properties"]["kind"] == "building" for f in assets["features"]) == parsed["building_way_count"]
    from shapely.geometry import shape
    perimeter = shape(json.loads(Path(path).read_text())["features"][index]["geometry"])
    assert all(perimeter.buffer(1e-7).covers(shape(f["geometry"])) for f in assets["features"])
    print(f"  [PASS] {parsed['building_way_count']} building ways, {parsed['road_km']:.2f} km roads, "
          f"{len(parsed['places'])} place points; geometry clipped to perimeter")
    return parsed


async def test_get_fire_weather(session: ClientSession) -> dict:
    """Real archive request: Evia weather, not a fabricated fire perimeter."""
    _section("TEST: get_fire_weather (Evia, 2021-08-05)")
    result = await session.call_tool("get_fire_weather", {
        "latitude": 38.8, "longitude": 23.3, "start_date": "2021-08-05",
    })
    parsed = json.loads(result.content[0].text)
    assert parsed.get("ok"), parsed
    assert len(parsed["hourly"]["time"]) == 24
    assert parsed["hourly"]["time"][0] == "2021-08-05T00:00"
    assert parsed["hourly"]["time"][-1] == "2021-08-05T23:00"
    assert parsed["hourly_units"]["wind_speed_10m"] == "m/s"
    assert parsed["timezone"] == "UTC"
    assert len(parsed["antecedent_daily"]["time"]) == 30
    assert parsed["antecedent_daily"]["time"][-1] == "2021-08-04"
    rain = parsed["antecedent_daily"]["precipitation_sum"]
    assert parsed["antecedent_rain_mm"] == (sum(rain) if None not in rain else None)
    assert parsed["warnings"] and parsed["attribution"]
    print("  [PASS] live ERA5 via MCP: event hours, preceding rain, UTC and units")
    return parsed


# ---------------------------------------------------------------------------
# Offline unit tests (no server needed)
# ---------------------------------------------------------------------------


def run_unit_tests():
    """Run offline unit tests for VRR and severity map."""
    import numpy as np

    sys.path.insert(0, str(SERVER_DIR))
    from server import (
        _compute_severity_map,
        _expand_bbox_km,
        _split_antimeridian_bbox,
        build_recovery_table,
        get_fire_weather,
        get_fire_exposure,
    )

    invalid = json.loads(asyncio.run(get_fire_exposure("not-a-perimeter.txt", 0)))
    assert invalid["ok"] is False and invalid["error_type"] == "invalid_perimeter"
    _section("UNIT TEST: weather input validation (no network)")
    for overrides in [
        {"latitude": float("nan")}, {"longitude": 181},
        {"start_date": "2021-02-30"}, {"start_date": "2021-8-5"},
        {"start_date": "2999-01-01"}, {"start_date": "1940-01-01"},
        {"end_date": "2021-08-04"}, {"end_date": "2021-09-05"},
        {"lookback_days": 0}, {"lookback_days": 91},
    ]:
        args = {"latitude": 38.8, "longitude": 23.3, "start_date": "2021-08-05"}
        result = json.loads(asyncio.run(get_fire_weather(**(args | overrides))))
        assert result["ok"] is False and result["error_type"].startswith("invalid_"), result
    print("  [PASS] invalid coordinates, dates and request sizes rejected")

    # --- Severity map ---
    _section("UNIT TEST: _compute_severity_map (Key & Benson 2006)")

    pre = np.array([0.05, 0.20, 0.40, 0.60, 0.80], dtype=np.float32)
    post = np.array([0.05, 0.05, 0.05, 0.05, 0.05], dtype=np.float32)
    sev = _compute_severity_map(pre, post)
    expected = [0, 1, 2, 3, 4]
    assert sev.tolist() == expected, f"Severity mismatch: {sev.tolist()} != {expected}"
    print(f"  dNBR:     {(pre - post).tolist()}")
    print(f"  Severity: {sev.tolist()}")

    pre_gap = pre.copy()
    pre_gap[0] = np.nan
    sev_gap = _compute_severity_map(pre_gap, post)
    assert sev_gap[0] == 5, f"Invalid pixel should be class 5 (no data), got {sev_gap[0]}"
    assert sev_gap[1:].tolist() == expected[1:]
    print("  [PASS] severity map correct (class 5 = no data, not unburned)")

    # --- VRR / recovery table ---
    _section("UNIT TEST: build_recovery_table (VRR — Lin et al. 2005)")

    H, W = 20, 20
    bands = {"red": 0, "nir": 1}

    def _make_img(red_val: float, nir_val: float) -> np.ndarray:
        img = np.zeros((2, H, W), dtype=np.float32)
        img[0] = red_val
        img[1] = nir_val
        return img

    img_pre = _make_img(0.05, 0.45)    # NDVI = 0.8
    img_dist = _make_img(0.20, 0.30)   # NDVI = 0.2
    img_half = _make_img(0.10, 0.40)   # NDVI = 0.6  -> VRR ~66.67%
    img_full = _make_img(0.05, 0.45)   # NDVI = 0.8  -> VRR = 100%
    img_over = _make_img(0.03, 0.47)   # NDVI = 0.88 -> VRR > 100%

    burn_mask = np.ones((H, W), dtype=bool)
    severity_map = _compute_severity_map(
        np.full((H, W), 0.5, dtype=np.float32),
        np.full((H, W), 0.1, dtype=np.float32),
    )

    df = build_recovery_table(
        img_pre, img_dist,
        {"T+12mo": img_half, "T+24mo": img_full, "T+36mo": img_over},
        burn_mask, bands, severity_map,
    )

    vrr_12 = df.loc[df["Time step"] == "T+12mo", "VRR (%)"].values[0]
    vrr_24 = df.loc[df["Time step"] == "T+24mo", "VRR (%)"].values[0]
    vrr_36 = df.loc[df["Time step"] == "T+36mo", "VRR (%)"].values[0]

    assert 60 < vrr_12 < 70, f"Expected VRR ~66.67%, got {vrr_12}"
    assert 99 < vrr_24 < 101, f"Expected VRR ~100%, got {vrr_24}"
    assert vrr_36 > 100, f"Expected VRR >100%, got {vrr_36}"

    print(f"  T+12mo: VRR={vrr_12:.2f}% (expected ~66.67%)")
    print(f"  T+24mo: VRR={vrr_24:.2f}% (expected ~100%)")
    print(f"  T+36mo: VRR={vrr_36:.2f}% (expected >100%)")

    assert "% Very poor" in df.columns and "% Excellent" in df.columns
    pct_good_12 = df.loc[df["Time step"] == "T+12mo", "% Good"].values[0]
    assert pct_good_12 == 100.0, f"Expected 100% Good at T+12mo, got {pct_good_12}"
    print("  Classification columns correct")

    # Guard condition: NDVI_pre ~ NDVI_dist -> NaN
    img_same = _make_img(0.20, 0.30)
    df_guard = build_recovery_table(
        img_same, img_dist, {"T+12mo": img_half}, burn_mask, bands, severity_map,
    )
    vrr_guard = df_guard.loc[0, "VRR (%)"]
    assert np.isnan(vrr_guard), f"Expected NaN when denom ~ 0, got {vrr_guard}"
    print("  Denominator guard (NaN) correct")

    print("  [PASS] all VRR tests passed")

    # --- Geodesic bbox (Karney 2013 via pyproj.Geod.fwd) ---
    _section("UNIT TEST: geodesic bbox buffer and antimeridian split")

    boxes = _expand_bbox_km(23.7, 37.9, 23.8, 38.0, 1.0)
    assert len(boxes) == 1, boxes
    west, south, east, north = boxes[0]
    assert south < 37.9 and north > 38.0 and west < 23.7 and east > 23.8, boxes
    # ~1 km is about 0.009 degrees of latitude
    assert 37.9 - south < 0.02 and north - 38.0 < 0.02, boxes
    print(f"  1 km buffer: {boxes[0]}")

    split = _split_antimeridian_bbox(170.0, -10.0, -170.0, 10.0)
    assert split == [
        (170.0, -10.0, 180.0, 10.0),
        (-180.0, -10.0, -170.0, 10.0),
    ], split
    print(f"  antimeridian split: {split}")
    print("  [PASS] geodesic bbox helpers")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_tests(
    port: int,
    headers: dict[str, str],
    run_metrics: bool,
    weather_only: bool = False,
    exposure_file: str | None = None,
    feature_index: int = 0,
    air_quality_only: bool = False,
) -> bool:
    """Connect to the local server and run all tests."""
    mcp_url = f"http://localhost:{port}/mcp"

    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(TOOL_TIMEOUT)) as http:
        async with streamable_http_client(mcp_url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                await test_list_tools(session)
                if air_quality_only:
                    await test_community_air_quality(session)
                    return True
                await test_get_fire_weather(session)
                if exposure_file:
                    await test_get_fire_exposure(session, exposure_file, feature_index)
                if weather_only or exposure_file:
                    return True
                await test_geocode_place(session)
                await test_get_effis_burnt_areas(session)

                if run_metrics:
                    await test_compute_metrics(session)
                else:
                    _section("SKIP: compute_metrics (no CDSE credentials provided)")
                    print("  Pass --cdse-client-id and --cdse-client-secret to enable.")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Integration test for the Fire Detection MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick test (geocode + burnt areas — no creds needed):
  python test.py

  # Full test with CDSE credentials:
  python test.py --cdse-client-id ID --cdse-client-secret SECRET

  # Offline unit tests (no server, no network):
  python test.py --unit-tests
        """,
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to run the test server on (default: {DEFAULT_PORT})")
    parser.add_argument("--air-quality-only", action="store_true", help="Test real CAMS/ERA5 community context via MCP")
    parser.add_argument("--exposure-file", help="Test exposure on a real EFFIS GeoJSON (also tests weather)")
    parser.add_argument("--feature-index", type=int, default=0, help="Feature index in --exposure-file")
    parser.add_argument("--weather-only", action="store_true",
                        help="Test real Open-Meteo weather over MCP without EFFIS/CDSE calls")
    parser.add_argument("--unit-tests", action="store_true",
                        help="Run offline unit tests only (VRR, severity map)")

    cred_group = parser.add_argument_group(
        "credentials",
        "CDSE credentials for compute_metrics (otherwise loaded from .env / env vars). "
        "When provided, they are sent both as env vars to the server and as HTTP "
        "headers to the MCP client to test the credential proxy flow.",
    )
    cred_group.add_argument("--cdse-client-id", default=None,
                            help="CDSE OAuth client ID")
    cred_group.add_argument("--cdse-client-secret", default=None,
                            help="CDSE OAuth client secret")

    args = parser.parse_args()

    # --- Offline unit tests ---
    if args.unit_tests:
        run_unit_tests()
        _section("DONE — all unit tests passed")
        return

    # --- Determine if CDSE credentials are available ---
    cdse_id = args.cdse_client_id or os.getenv("CDSE_CLIENT_ID", "")
    cdse_secret = args.cdse_client_secret or os.getenv("CDSE_CLIENT_SECRET", "")
    run_metrics = bool(cdse_id and cdse_secret)

    # Build env overrides for the server subprocess
    env_overrides: dict[str, str] = {}
    if args.cdse_client_id:
        env_overrides["CDSE_CLIENT_ID"] = args.cdse_client_id
    if args.cdse_client_secret:
        env_overrides["CDSE_CLIENT_SECRET"] = args.cdse_client_secret

    # Build custom headers for the MCP client (per-request credential proxy)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if args.cdse_client_id:
        headers["X-CDSE-Client-Id"] = args.cdse_client_id
    if args.cdse_client_secret:
        headers["X-CDSE-Client-Secret"] = args.cdse_client_secret

    # --- Start server, run tests, stop server ---
    _section("Starting Fire Detection MCP Server")
    print(f"  port:    {args.port}")
    print(f"  server:  {SERVER_PY}")
    print(f"  metrics: {'yes (CDSE credentials available)' if run_metrics else 'skipped (no CDSE credentials)'}")
    if env_overrides:
        print(f"  env:     {', '.join(env_overrides.keys())}")
    if any(k.startswith("X-") for k in headers):
        print(f"  headers: {', '.join(k for k in headers if k.startswith('X-'))}")

    proc = _start_server(args.port, env_overrides)
    try:
        asyncio.run(_wait_for_server(f"http://localhost:{args.port}/mcp"))
        print("  Server is up.\n")

        ok = asyncio.run(run_tests(
            port=args.port,
            headers=headers,
            run_metrics=run_metrics,
            weather_only=args.weather_only,
            exposure_file=args.exposure_file,
            feature_index=args.feature_index,
            air_quality_only=args.air_quality_only,
        ))

        _section("DONE — all tests passed" if ok else "DONE — some tests failed")

    except TimeoutError:
        print(f"\n  [FAIL] Server did not start within {STARTUP_TIMEOUT}s")
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        if stderr:
            print(f"\n  Server stderr:\n{stderr[:2000]}")
        sys.exit(1)

    except Exception as exc:
        print(f"\n  [FAIL] {exc}")
        sys.exit(1)

    finally:
        _stop_server(proc)
        print("  Server stopped.")


if __name__ == "__main__":
    main()
