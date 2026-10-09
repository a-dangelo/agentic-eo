"""Test the fire-emissions MCP server in two parts.

Part 1, step by step: call each tool yourself on one example (the August 2021
north Evia fire) and pass each output into the next tool.

Part 2, ask the model: send a plain question to the EVE model (EVE-Instruct,
fine-tuned from Mistral Small) with our tools plus the registry's EFFIS tools,
and let the model decide which tools to call.

Usage:
    python test.py                         # part 1 and part 2
    python test.py --steps-only            # part 1 only (no EVE key needed)
    python test.py --ask "your question"   # part 2 with your own question
    python test.py --url http://localhost:8000/mcp   # use a running HTTP server

Part 2 reads EVE_API_BASE_URL, EVE_API_KEY and EVE_LLM_MODEL from the .env file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

HERE = Path(__file__).resolve().parent

# The August 2021 north Evia fire, as returned by EFFIS get_effis_burnt_areas.
EVIA_BBOX = "23.1766,38.7022,23.4614,39.0379"
EVIA_AREA_HA = 51881
EVIA_DATE = "2021-08-03"

DEFAULT_QUESTION = (
    "How much CO2, carbon monoxide, methane and smoke did the August 2021 wildfire in north Evia, "
    "Greece release? Is the smoke visible in air-quality data? Write a short briefing with sources."
)

SYSTEM_PROMPT = (
    "You are an Earth Observation analyst who reports the climate impact of wildfires. "
    "Use the tools to answer. Do not invent numbers. Cite the tool each fact came from.\n"
    "Workflow:\n"
    "1. Find the fire with get_effis_burnt_areas. Use buffer_km=0 and a date filter that matches the question "
    "(YYYY, YYYY-MM or YYYY-MM-DD). If you only have a place name, call geocode_place first to get its bbox. "
    "Never invent a bbox: if geocode_place returns a tiny box, geocode the wider area "
    "(for example the island or region) and pick the matching fire from the EFFIS results.\n"
    "If get_effis_burnt_areas returns no fires (for example outside Europe), call detect_burned_area "
    "with a bbox around the place (geocode_place with buffer_km=50) and the month (YYYY-MM), "
    "then use its burned_area_ha, bbox and first_burn_date in the next steps.\n"
    "2. Call get_burn_fuel_types with that fire's bbox.\n"
    "3. Call estimate_fire_emissions with the fire's area_ha, its bbox, and fuel_shares_pct from step 2.\n"
    "4. Call get_smoke_signal with the fire's bbox and firedate.\n"
    "Report every emission as a central value with its low-high range, add the CO2-equivalent and car-years, "
    "and end with the caveats the tools return."
)


def load_env() -> None:
    """Load the nearest .env (this folder or a parent) without overriding real environment variables."""
    for folder in [HERE, *HERE.parents]:
        env_file = folder / ".env"
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() and not key.lstrip().startswith("#"):
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            return


async def open_fire_server(stack: AsyncExitStack, url: str | None) -> ClientSession:
    """Connect to our server: over HTTP if a URL is given, otherwise start server.py as a subprocess (stdio)."""
    if url:
        read, write, _ = await stack.enter_async_context(streamablehttp_client(url))
    else:
        params = StdioServerParameters(command=sys.executable, args=[str(HERE / "server.py"), "--transport", "stdio"])
        read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


async def call(session: ClientSession, tool: str, arguments: dict) -> dict:
    """Call one tool and decode its JSON result."""
    result = await session.call_tool(tool, arguments)
    return json.loads(result.content[0].text)


def show(title: str, data: dict) -> None:
    print(f"\n--- {title}")
    print(json.dumps(data, indent=1, ensure_ascii=False)[:1500])


# ---------------------------------------------------------------------------
# Part 1: step by step
# ---------------------------------------------------------------------------

async def run_steps(session: ClientSession) -> None:
    print("=" * 70)
    print("PART 1: call each tool step by step (north Evia fire, August 2021)")
    print("=" * 70)

    tools = await session.list_tools()
    print("tools on our server:", [t.name for t in tools.tools])

    print(f"\nInput from EFFIS: bbox={EVIA_BBOX}, area_ha={EVIA_AREA_HA}, firedate={EVIA_DATE}")

    # Step 0: detect the burned area ourselves (the fallback when EFFIS has no record).
    detected = await call(session, "detect_burned_area", {"bbox": EVIA_BBOX, "month": EVIA_DATE[:7]})
    show("Step 0: detect_burned_area (MODIS, global)", detected)
    print(f"   MODIS {detected['burned_area_ha']:,.0f} ha vs EFFIS {EVIA_AREA_HA:,} ha")

    # Step 1: what burned?
    fuel = await call(session, "get_burn_fuel_types", {"bbox": EVIA_BBOX})
    show("Step 1: get_burn_fuel_types", fuel)

    # Step 2: how much gas? Uses the fuel shares from step 1.
    emissions = await call(session, "estimate_fire_emissions", {
        "burned_area_ha": EVIA_AREA_HA,
        "bbox": EVIA_BBOX,
        "fuel_shares_pct": fuel["fuel_shares_pct"],
    })
    show("Step 2: estimate_fire_emissions", {
        k: emissions[k] for k in ("emissions_tonnes", "co2_equivalent_tonnes", "car_years_equivalent")
    })

    # Step 3: is the smoke visible in the air?
    smoke = await call(session, "get_smoke_signal", {"bbox": EVIA_BBOX, "fire_date": EVIA_DATE})
    show("Step 3: get_smoke_signal", smoke["pollutants"])

    # Step 4: a bad input must return a clear error, not a crash.
    bad = await call(session, "get_burn_fuel_types", {"bbox": "not-a-bbox"})
    assert "error" in bad, "a bad bbox should return an error"
    show("Step 4: error handling (bad bbox)", bad)

    co2 = emissions["emissions_tonnes"]["CO2"]
    print(f"\nSummary: about {co2['central']:,.0f} t CO2 (range {co2['low']:,.0f} to {co2['high']:,.0f}), "
          f"CO peak {smoke['pollutants']['carbon_monoxide']['peak_vs_baseline']}x normal.")


# ---------------------------------------------------------------------------
# Part 2: ask the EVE (Mistral-based) model, which picks the tools itself
# ---------------------------------------------------------------------------

async def run_agent(fire_session: ClientSession, stack: AsyncExitStack, question: str, max_steps: int = 12) -> None:
    print("\n" + "=" * 70)
    print("PART 2: ask the EVE model (Mistral-based) and let it call the tools")
    print("=" * 70)

    api = os.getenv("EVE_API_BASE_URL", "").rstrip("/")
    key = os.getenv("EVE_API_KEY", "")
    model = os.getenv("EVE_LLM_MODEL", "jsc/alias-eve")
    if not (api and key):
        print("Skipped: set EVE_API_BASE_URL and EVE_API_KEY in .env to run part 2.")
        return

    # The registry's EFFIS server, reached through EVE's MCP gateway with the same key.
    read, write, _ = await stack.enter_async_context(
        streamablehttp_client(f"{api}/mcp/effis", headers={"Authorization": f"Bearer {key}"}, timeout=180)
    )
    effis_session = await stack.enter_async_context(ClientSession(read, write))
    await effis_session.initialize()

    # Map every tool name to the server that owns it, and describe the tools in the
    # OpenAI "function calling" format that the EVE chat endpoint understands.
    route: dict[str, ClientSession] = {}
    tools = []
    for session in (fire_session, effis_session):
        for tool in (await session.list_tools()).tools:
            route[tool.name] = session
            tools.append({"type": "function", "function": {
                "name": tool.name, "description": tool.description or "", "parameters": tool.inputSchema,
            }})
    print("tools given to the model:", list(route))
    print(f"\nYou: {question}")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
    async with httpx.AsyncClient(timeout=300) as http:
        for _ in range(max_steps):
            resp = await http.post(
                f"{api}/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "messages": messages, "tools": tools, "temperature": 0.1, "max_tokens": 2048},
            )
            resp.raise_for_status()
            message = resp.json()["choices"][0]["message"]
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                print(f"\nModel:\n{message.get('content', '')}")
                return

            if message.get("content"):
                print(f"\nModel (thinking): {message['content']}")
            for tc in tool_calls:
                name = tc["function"]["name"]
                args = tc["function"].get("arguments") or "{}"
                args = json.loads(args) if isinstance(args, str) else args
                print(f"\n  -> {name}({json.dumps(args, ensure_ascii=False)})")
                if name in route:
                    result = await route[name].call_tool(name, args)
                    text = "".join(getattr(block, "text", "") for block in result.content)
                else:
                    text = json.dumps({"error": f"Unknown tool {name}."})
                print(f"     <- {text[:300]}{'...' if len(text) > 300 else ''}")
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": text})

    print(f"\nStopped after {max_steps} model steps without a final answer.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test the fire-emissions MCP server")
    parser.add_argument("--url", help="URL of a running server, e.g. http://localhost:8000/mcp (default: start server.py)")
    parser.add_argument("--steps-only", action="store_true", help="run part 1 only")
    parser.add_argument("--ask", default=DEFAULT_QUESTION, help="question for part 2")
    args = parser.parse_args()
    load_env()

    async with AsyncExitStack() as stack:
        fire_session = await open_fire_server(stack, args.url)
        await run_steps(fire_session)
        if not args.steps_only:
            await run_agent(fire_session, stack, args.ask)


if __name__ == "__main__":
    asyncio.run(main())
