# Agentic EO hackathon

Starter kit for the internal **Agentic AI for Earth Observation** hackathon.

## Organizers

This event is organized by [Pi School](https://picampus-school.com/), in collaboration with [ESA Φ-lab](https://philab.esa.int/), as part of the [EVE project](https://eve.philab.esa.int/about).

The day is one Earth Observation question the agent cannot answer yet. You build the missing [MCP](https://modelcontextprotocol.io/) server, test it against the live agent, and open a pull request to the [EVE MCP tool registry](https://github.com/eve-esa/mcp-tool-registry) so the same tool can be called from more than one client.

The programme, the worked example, delivery, and how to open that pull request are in [`START_HERE.ipynb`](START_HERE.ipynb). This page is the map of the repository.

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
git clone https://github.com/eve-esa/agentic-eo-hackathon && cd agentic-eo-hackathon
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
