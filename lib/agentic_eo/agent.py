"""A ReAct agent over MCP tools.

Same assembly as Section III of the Earthrise notebook: discover tools with
``MultiServerMCPClient``, keep the conversation in ``MemorySaver``, build the loop
with ``create_agent``, then ``chat``.

https://docs.langchain.com/oss/python/langchain/agents
https://arxiv.org/abs/2210.03629
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastmcp import FastMCP

_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _chunk_text(content: Any) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            parts.append(block.get("text") or "")
        else:
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def _tool_call(call: Any) -> dict[str, Any]:
    if isinstance(call, dict):
        return {"name": call.get("name", ""), "args": call.get("args") or {}}
    return {"name": getattr(call, "name", "") or "", "args": getattr(call, "args", None) or {}}


def _trace_from_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Build a trace from the graph's saved messages when stream events were not recorded."""
    steps: list[dict[str, Any]] = []
    for message in messages:
        kind = getattr(message, "type", "")
        if kind == "ai":
            steps.append({
                "node": "agent",
                "role": "assistant",
                "latency_s": 0.0,
                "content": _THINK.sub("", _chunk_text(getattr(message, "content", None))).strip(),
                "tool_calls": [_tool_call(call) for call in (getattr(message, "tool_calls", None) or [])],
            })
        elif kind == "tool":
            steps.append({
                "node": "tools",
                "role": "tool",
                "name": getattr(message, "name", "") or "",
                "latency_s": 0.0,
                "content": _chunk_text(getattr(message, "content", None)),
            })
    return steps


def _tool_output_text(output: Any) -> str:
    content = getattr(output, "content", output)
    if isinstance(content, str):
        return content
    text = _chunk_text(content)
    if text:
        return text
    return json.dumps(content, default=str)


@dataclass
class ChatResult:
    """One ``chat`` turn. ``str(result)`` is the answer. ``result.trace`` is what ``show_trace`` draws."""

    query: str
    answer: str
    trace: list[dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        return self.answer


class Agent:
    """One ReAct agent. ``chat`` sends a turn. ``reset`` forgets the conversation. ``close`` stops the notebook MCP servers."""

    def __init__(self, graph, thread_id: str, tool_names: list[str], notebook_servers: list[Any]):
        self._graph = graph
        self._thread_id = thread_id
        self.tool_names = tool_names
        self._notebook_servers = notebook_servers
        self._closed = False

    def _config(self) -> dict:
        return {"configurable": {"thread_id": self._thread_id}}

    async def chat(self, query: str, *, echo: bool = True) -> ChatResult:
        """Send one user message. Prints the turn when ``echo`` is true.

        Returns a :class:`ChatResult`. Pass it to ``show_trace`` for the timeline.
        The trace uses the same step shape as the EVE platform tour: ``node`` is
        ``agent`` or ``tools``, with ``latency_s``, ``content``, and ``tool_calls``.
        """
        if self._closed:
            raise RuntimeError("This agent is closed. Call create_agent() again.")
        from langchain_core.messages import HumanMessage

        if echo:
            print(f"You: {query}")
            print("Agent: ", end="", flush=True)

        answer = ""
        trace: list[dict[str, Any]] = []
        model_started: dict[str, float] = {}
        model_text: dict[str, str] = {}
        tool_started: dict[str, float] = {}
        tools_since_agent = 0

        async for event in self._graph.astream_events(
            {"messages": [HumanMessage(content=query)]},
            self._config(),
            version="v2",
        ):
            kind = event.get("event")
            run_id = event.get("run_id", "")
            if kind == "on_chat_model_start":
                model_started[run_id] = time.perf_counter()
            elif kind == "on_chat_model_stream":
                text = _chunk_text(event["data"]["chunk"].content)
                if text:
                    answer += text
                    model_text[run_id] = model_text.get(run_id, "") + text
                    if echo:
                        print(text, end="", flush=True)
            elif kind == "on_chat_model_end":
                output = event["data"].get("output")
                content = _THINK.sub("", _chunk_text(getattr(output, "content", None)) or model_text.get(run_id, "")).strip()
                calls = [_tool_call(call) for call in (getattr(output, "tool_calls", None) or [])]
                started = model_started.pop(run_id, None)
                trace.append({
                    "node": "agent",
                    "role": "assistant",
                    "latency_s": (time.perf_counter() - started) if started else 0.0,
                    "content": content,
                    "tool_calls": calls,
                })
                tools_since_agent = 0
            elif kind == "on_tool_start":
                name = event.get("name", "")
                args = event["data"].get("input") or {}
                tool_started[run_id] = time.perf_counter()
                if trace and trace[-1]["node"] == "agent" and tools_since_agent >= len(trace[-1]["tool_calls"]):
                    trace[-1]["tool_calls"].append({"name": name, "args": args if isinstance(args, dict) else {}})
                tools_since_agent += 1
                if echo:
                    print(f"\n  [{name}]")
                    if isinstance(args, dict):
                        for key, value in args.items():
                            print(f"    {key}: {str(value)[:120]}")
            elif kind == "on_tool_end":
                started = tool_started.pop(run_id, None)
                trace.append({
                    "node": "tools",
                    "role": "tool",
                    "name": event.get("name", ""),
                    "latency_s": (time.perf_counter() - started) if started else 0.0,
                    "content": _tool_output_text(event["data"].get("output")),
                })
                if echo:
                    print(f"  [{event.get('name', '')} done]")

        answer = _THINK.sub("", answer).strip()
        state = await self._graph.aget_state(self._config())
        messages = (state.values.get("messages") or []) if state.values else []
        if not trace and messages:
            trace = _trace_from_messages(messages)
        if not answer and messages:
            answer = _THINK.sub("", _chunk_text(messages[-1].content)).strip()
            if echo and answer:
                print(answer, end="", flush=True)
        if echo:
            print()
        return ChatResult(query=query, answer=answer, trace=trace)

    def reset(self) -> str:
        """Forget this conversation. The MCP server stays up. Returns the new thread id."""
        self._thread_id = uuid.uuid4().hex
        return self._thread_id

    async def close(self) -> None:
        """Stop notebook MCP servers when this is the last agent using them."""
        if self._closed:
            return
        self._closed = True
        from .mcp_tools import release_notebook_server

        for running in self._notebook_servers:
            await release_notebook_server(running)


async def create_agent(servers: list, *,
                       prompt: str | None = None,
                       thread_id: str | None = None) -> Agent:
    """Build a ReAct agent on EVE and every server in ``servers``.

    Each entry is a notebook ``FastMCP`` instance (started here, stopped by
    ``Agent.close``), an EVE registry name such as ``"effis"``, an ``http://…/mcp`` URL,
    or a path to ``server.py``. Registry names are called through EVE's MCP gateway.
    ``prompt`` is the system prompt. ``reset`` starts a
    fresh thread. ``close`` stops notebook servers.

    The loop itself is LangChain's ``create_agent``:
    https://docs.langchain.com/oss/python/langchain/agents
    """
    from langchain.agents import create_agent as build_react_agent
    from langgraph.checkpoint.memory import MemorySaver

    from .eve import eve_llm
    from .mcp_tools import acquire_notebook_server, mcp_tools_for_agent, release_notebook_server

    notebooks: list[Any] = []
    resolved: list[Any] = []
    try:
        for server in servers:
            if isinstance(server, FastMCP):
                running = await acquire_notebook_server(server)
                notebooks.append(running)
                resolved.append(running.url)
            else:
                resolved.append(server)
        tools = await mcp_tools_for_agent(resolved)
    except Exception:
        for running in notebooks:
            await release_notebook_server(running)
        raise

    graph = build_react_agent(
        model=eve_llm(temperature=0),
        tools=tools,
        system_prompt=prompt,
        checkpointer=MemorySaver(),
    )
    return Agent(
        graph,
        thread_id or uuid.uuid4().hex,
        [tool.name for tool in tools],
        notebooks,
    )
