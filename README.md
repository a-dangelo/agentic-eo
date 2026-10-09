# Agentic EO hackathon

Starter kit for the internal **Agentic AI for Earth Observation** hackathon.

## Organizers

This event is organized by [Pi School](https://picampus-school.com/), in collaboration with [ESA Φ-lab](https://philab.esa.int/), as part of the [EVE project](https://eve.philab.esa.int/about).

The day is one Earth Observation question the agent cannot answer yet. You build the missing [MCP](https://modelcontextprotocol.io/) server, test it against the live agent, and open a pull request to the [EVE MCP tool registry](https://github.com/eve-esa/mcp-tool-registry) so the same tool can be called from more than one client.

The programme, the worked example, delivery, and how to open that pull request are in [`START_HERE.ipynb`](START_HERE.ipynb). This page is the map of the repository.

## Our submission: fire exposure, weather and community air quality

Download [`agentic-eo-submission.zip`](agentic-eo-submission.zip) for upload. It includes `START_HERE_FINAL.ipynb`, Sameer’s original workflow followed by our added section, plus code and the real demo snapshot. The original notebooks are preserved. The combined notebook has not yet been run on SageMaker; Sameer’s original flow was tested there, and our additions were tested locally.

In `START_HERE_FINAL.ipynb`, run the setup cell, then **Which places and assets overlap this fire?** It selects an EFFIS perimeter, maps OSM building/road exposure and named place points, plots historical weather, compares modeled PM₂.₅/CO at Agia Anna with the preceding week, and asks EVE for a briefing. The trace checks that all three new tools succeeded.

The extended server is included in `servers/effis/`; no sibling checkout is needed. `get_fire_exposure` uses a timestamped OSM snapshot; `get_fire_weather` uses Open-Meteo ERA5; `get_community_air_quality` compares CAMS Europe concentrations against a seven-day baseline and reports coarse wind alignment. These describe mapped exposure and modeled conditions, not damage, population impacts or proof that this fire caused pollution. EVE's model calls our local server; the hosted registry has not been updated.

Extract the upload ZIP into one folder on the lab machine and follow `UPLOAD.txt`. Keep `lib/`, `servers/`, `scratch/` and `requirements.txt` beside the final notebook. Install dependencies in the notebook kernel’s environment. Keep the lab's own `.env`; do not upload or share yours. Each teammate needs their own EVE key. Check EVE’s prose against the result tables: generated summaries can misstate ratios.

Checks: `uv run python servers/effis/test.py --unit-tests` (offline), `--weather-only` (live weather) or `--air-quality-only` (live modeled pollution) with the same test script. The notebook itself runs the real exposure and EVE checks. `test.ipynb` is the separate teammate experiment and is not needed for this demo.

## What's inside

```
.
├── START_HERE.ipynb          # the lab: example, your turn, pull request, use cases
├── MCP-Handbook.ipynb        # longer background on MCP and the agent loop
├── examples/geocode-server/  # the Nominatim example as a standalone server.py
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

## Funding

This project is supported by the European Space Agency (ESA) Φ-lab through the Large Language Model for Earth Observation and Earth Science project, as part of the Foresight Element within FutureEO Block 4 programme.

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
