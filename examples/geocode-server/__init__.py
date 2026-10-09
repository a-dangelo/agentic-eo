"""Helpers for the Agentic EO hackathon lab.

Import from a notebook anywhere in the repo with:

    import sys, pathlib; sys.path.insert(0, str(pathlib.Path.cwd().parents[0] / "lib"))  # examples/
    from agentic_eo import settings, eve_llm, ...

START_HERE.ipynb and the examples already do this for you.
"""

from .agent import Agent, create_agent
from .env import REPO_ROOT, Settings, masked, settings
from .eve import EveUnavailable, eve_hello, eve_llm, list_eve_mcp_servers
from .mcp_tools import (
    ask,
    call_tool,
    eve_mcp_client,
    local_server_client,
    mcp_tools_for_agent,
    pretty_print_mcp_servers,
    registry_server_client,
)
from .trace import show_trace

__all__ = [
    "REPO_ROOT",
    "Agent",
    "EveUnavailable",
    "Settings",
    "ask",
    "call_tool",
    "eve_hello",
    "eve_llm",
    "eve_mcp_client",
    "list_eve_mcp_servers",
    "local_server_client",
    "masked",
    "mcp_tools_for_agent",
    "pretty_print_mcp_servers",
    "registry_server_client",
    "create_agent",
    "settings",
    "show_trace",
]
