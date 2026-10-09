"""The EVE model and platform, reached through EVE's API gateway.

- LLM: OpenAI-compatible endpoint at {EVE_API_BASE_URL}/v1 (chat completions),
  authenticated with your EVE API key (Bearer eve_...).
- Tools: EVE's MCP gateway at {EVE_API_BASE_URL}/mcp/{server_name}, same key.
- Catalogue of registry servers: GET {EVE_API_BASE_URL}/mcp-servers.
"""

from __future__ import annotations

import httpx

from .env import settings


class EveUnavailable(RuntimeError):
    """EVE is not configured or not reachable. Notebooks print a friendly message."""


def _require_eve() -> None:
    if not settings.eve_configured:
        raise EveUnavailable(
            "EVE is not configured in this environment (EVE_API_BASE_URL / EVE_API_KEY missing "
            "in ~/agentic-eo/.env). Ask a mentor at the help desk."
        )


def eve_llm(temperature: float = 0.1, max_tokens: int = 2048, **kwargs):
    """A LangChain chat model backed by EVE (OpenAI-compatible gateway)."""
    _require_eve()
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=settings.eve_llm_base_url,
        api_key=settings.eve_api_key,
        model=settings.eve_llm_model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=120,
        max_retries=1,
        **kwargs,
    )


def eve_hello(question: str = "In two sentences: what is Sentinel-2 used for?") -> str:
    """Ask EVE one question and return the answer text."""
    llm = eve_llm()
    try:
        return llm.invoke(question).content
    except Exception as exc:  # network, auth, cold start...
        raise EveUnavailable(f"EVE did not answer: {exc}") from exc


def list_eve_mcp_servers(limit: int = 50) -> list[dict]:
    """Registry MCP servers that EVE can reach for you (name, description, enabled)."""
    _require_eve()
    try:
        resp = httpx.get(
            f"{settings.eve_api_base_url}/mcp-servers",
            params={"limit": limit, "page": 1},
            headers={"Authorization": f"Bearer {settings.eve_api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise EveUnavailable(f"Could not list EVE MCP servers: {exc}") from exc
    return [
        {"name": s.get("name"), "description": (s.get("description") or "").strip(),
         "enabled": s.get("enabled")}
        for s in resp.json().get("data", [])
    ]
