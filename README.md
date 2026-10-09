# Agentic EO hackathon

Starter kit for the internal **Agentic AI for Earth Observation** hackathon.

## Organizers

This event is organized by [Pi School](https://picampus-school.com/), in collaboration with [ESA Φ-lab](https://philab.esa.int/), as part of the [EVE project](https://eve.philab.esa.int/about).

The day is one Earth Observation question the agent cannot answer yet. You build the missing [MCP](https://modelcontextprotocol.io/) server, test it against the live agent, and open a pull request to the [EVE MCP tool registry](https://github.com/eve-esa/mcp-tool-registry) so the same tool can be called from more than one client.

The programme, the worked example, delivery, and how to open that pull request are in [`START_HERE.ipynb`](START_HERE.ipynb). This page is the map of the repository.

## Our submission: wildfire emissions and smoke

EFFIS tells the agent **where** a wildfire burned, **how big** it was and **when**. It cannot say what the fire released into the atmosphere. Our `fire-emissions` MCP server closes that gap: it takes the fire returned by EFFIS (`bbox`, `area_ha`, `firedate`) and adds what burned, the gases it released and whether the smoke shows in air-quality data. No account or API key is needed.

| Tool | Answers | Data source |
|---|---|---|
| `get_burn_fuel_types` | What burned (forest, shrub, grass, crops), from the land-cover map **before** the fire | [ESA WorldCover](https://planetarycomputer.microsoft.com/dataset/esa-worldcover) 2020/2021, Microsoft Planetary Computer statistics API |
| `estimate_fire_emissions` | Tonnes of CO₂, CO, CH₄, N₂O and PM2.5 (low, central, high), CO₂-equivalent and car-years | [IPCC 2006 Guidelines](https://www.ipcc-nggip.iges.or.jp/public/2006gl/vol4.html), Vol. 4, Eq. 2.27; emission factors from [Andreae and Merlet (2001)](https://doi.org/10.1029/2000GB001382) |
| `get_smoke_signal` | CO, PM2.5 and PM10 during the fire against the two weeks before | [CAMS](https://atmosphere.copernicus.eu/) via the [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api) |
| `detect_burned_area` | Burned area anywhere in the world, used when EFFIS has no record | [NASA MODIS Burned Area MCD64A1](https://planetarycomputer.microsoft.com/dataset/modis-64A1-061), Microsoft Planetary Computer |

The agent chains them after the registry's EFFIS server: `geocode_place` → `get_effis_burnt_areas` (or `detect_burned_area`) → `get_burn_fuel_types` → `estimate_fire_emissions` → `get_smoke_signal`. Land-cover classes are counted on Planetary Computer's servers, so no raster is downloaded.

**Result for the August 2021 north Evia fire** (EFFIS: 51,881 ha, started 3 August):

| | Low | Central | High |
|---|---|---|---|
| CO₂ (t) | 1,090,000 | 2,180,000 | 3,640,000 |
| CO (t) | 73,000 | 146,000 | 244,000 |
| CH₄ (t) | 3,190 | 6,370 | 10,600 |
| N₂O (t) | 178 | 356 | 594 |
| PM2.5 (t) | 8,770 | 17,500 | 29,300 |
| CO₂-equivalent (t, CO₂ + CH₄ + N₂O) | 1,220,000 | 2,450,000 | 4,080,000 |

Fuel: 85% tree cover (WorldCover 2020). Smoke: carbon monoxide peaked at 12.3 times its two-week baseline on 6 August 2021, PM2.5 at 7.5 times. MODIS gives 50,800 ha for the same fire, against EFFIS's 51,881 ha.

**Before and after.** With only the registry's EFFIS server, the agent finds the fire and then answers that it cannot compute the emissions (`compute_metrics` needs CDSE credentials and measures burn severity, not gases). With our server added, the same question returns the table above with its sources.

**Where it is.** In `START_HERE_FINAL.ipynb`, section 5 "Your turn": Cell A defines the server, Cell B calls each tool directly (no EVE tokens), Cell C is the agent with EFFIS and our server (after), Cell D the same question with EFFIS only (before). The same code is a standalone registry-ready server in [`examples/fire-emissions-server/`](examples/fire-emissions-server/) (`server.py`, `requirements.txt`, `test.py`); it passes the registry's `scripts/validate_pr.py`. `test.ipynb` walks through how MCP works, from a plain Python function to the model choosing the tools.

```bash
cd examples/fire-emissions-server
python test.py --steps-only   # call the four tools on the Evia fire, no EVE key needed
python test.py                # then ask the EVE model, which picks the tools itself (needs EVE_API_KEY)
python server.py              # serve the tools over HTTP at http://localhost:8000/mcp
```

**Limits.** Emissions are an order-of-magnitude estimate (about ±50%); fuel burned per hectare is the largest uncertainty, which is why every value is a range. Fuel shares describe the fire's bounding box, not only the burnt pixels. CAMS values are model concentrations on an 11 to 40 km grid: they show the smoke, they do not measure emissions. MODIS misses fires under about 25 ha and is published one to two months after the month ends. Vegetation CO₂ can be partly re-absorbed as the land regrows. Check the model's prose against the tool output: in one run it converted 12.3 times into a wrong percentage, which a prompt rule now prevents.

## Our submission: fire exposure, weather and community air quality

Download [`agentic-eo-submission.zip`](agentic-eo-submission.zip) for upload. It includes `START_HERE_FINAL.ipynb`, Sameer’s original workflow followed by our added section, plus code and the real demo snapshot. The original notebooks are preserved. The combined notebook has not yet been run on SageMaker; Sameer’s original flow was tested there, and our additions were tested locally.

In `START_HERE_FINAL.ipynb`, run the setup cell, then **Which places and assets overlap this fire?** It selects an EFFIS perimeter, maps OSM building/road exposure and named place points, plots historical weather, compares modeled PM₂.₅/CO at Agia Anna with the preceding week, and asks EVE for a briefing. The trace checks that all three new tools succeeded.

The extended server is included in `servers/effis/`; no sibling checkout is needed. `get_fire_exposure` uses a timestamped OSM snapshot; `get_fire_weather` uses Open-Meteo ERA5; `get_community_air_quality` compares CAMS Europe concentrations against a seven-day baseline and reports coarse wind alignment. These describe mapped exposure and modeled conditions, not damage, population impacts or proof that this fire caused pollution. EVE's model calls our local server; the hosted registry has not been updated.

Extract the upload ZIP into one folder on the lab machine and follow `UPLOAD.txt`. Keep `lib/`, `servers/`, `scratch/` and `requirements.txt` beside the final notebook. Install dependencies in the notebook kernel’s environment. Keep the lab's own `.env`; do not upload or share yours. Each teammate needs their own EVE key. Check EVE’s prose against the result tables: generated summaries can misstate ratios.

Checks: `uv run python servers/effis/test.py --unit-tests` (offline), `--weather-only` (live weather) or `--air-quality-only` (live modeled pollution) with the same test script. The notebook itself runs the real exposure and EVE checks. `test.ipynb` is the separate teammate experiment and is not needed for this demo.

## What's inside

```
.
├── START_HERE_FINAL.ipynb    # our combined submission: fire emissions, then exposure and air quality
├── START_HERE_SAMEER.ipynb   # the fire-emissions part on its own
├── test.ipynb                # how the fire-emissions MCP server works, step by step
├── MCP-Handbook.ipynb        # longer background on MCP and the agent loop
├── examples/geocode-server/  # the Nominatim example as a standalone server.py
├── examples/fire-emissions-server/  # our fire-emissions MCP server, ready for the registry
├── servers/effis/            # the extended EFFIS server (exposure, weather, community air quality)
├── lib/agentic_eo/           # notebook helpers: EVE client, MCP clients, agent, traces
├── images/                   # figures used in the notebook
├── requirements.txt          # packages for the lab kernel
└── .env.example              # variable names the notebook reads
```

## Where you work

You can do the whole day in the lab. Scan the QR code on the screen or on your table, enter the email you registered with, then the one-time code from that inbox. You land in a SageMaker JupyterLab space with this kit open, the **Agentic EO** kernel (Python 3.12), and GPUs on the instance. Open [`START_HERE.ipynb`](START_HERE.ipynb) and run it there. Your EVE API key is already in `.env` as `EVE_API_KEY`.

No code? Ask the help desk for a spare account.

You can also download this folder and work on your laptop, so you can use a coding assistant (Cursor, or another). The EVE API key still comes from the lab: copy `EVE_API_KEY` out of the lab `.env` into the `.env` on your machine. On a fresh clone:

```bash
git clone https://github.com/a-dangelo/agentic-eo && cd agentic-eo
uv venv -p 3.12 && uv pip install -r requirements.txt jupyterlab
cp .env.example .env   # paste EVE_API_KEY from the lab
uv run jupyter lab
```

What we review is the notebook on your SageMaker instance. If you change the notebook or the server code on your laptop, upload those files back into the lab before the end of the day.

## Citation

```bibtex
@misc{atrio2026evedomainspecificllmframework,
      title={{EVE}: A Domain-Specific {LLM} Framework for Earth Intelligence},
      author={Àlex R. Atrio and Antonio Lopez and Jino Rohit and Yassine El Ouahidi and Marcello Politi and Vijayasri Iyer and Umar Jamil and Sébastien Bratières and Nicolas Longépé},
      year={2026},
      eprint={2604.13071},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2604.13071},
}
```

## Links

- EVE: https://eve.philab.esa.int/
- EVE MCP tool registry: https://github.com/eve-esa/mcp-tool-registry
- Model Context Protocol: https://modelcontextprotocol.io/
