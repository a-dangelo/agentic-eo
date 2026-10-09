"""Lab settings, read from ~/agentic-eo/.env (written for you by the lab setup).

The lab file sets three EVE variables: ``EVE_API_BASE_URL``, ``EVE_API_KEY``, and
``EVE_LLM_MODEL``. The chat endpoint is ``{EVE_API_BASE_URL}/v1`` and the MCP
gateway is ``{EVE_API_BASE_URL}/mcp``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env", override=False)


def masked(secret: str | None) -> str:
    """Show only the start and end of a secret, e.g. 'eve_1a2b…9f0e'."""
    if not secret:
        return "(not set)"
    return secret[:6] + "…" + secret[-4:] if len(secret) > 12 else "***"


@dataclass(frozen=True)
class Settings:
    participant: str
    workshop_name: str
    user_bucket: str
    shared_bucket: str
    eve_api_base_url: str
    eve_api_key: str
    eve_llm_base_url: str
    eve_llm_model: str
    eve_mcp_base_url: str
    registry_dir: Path

    @classmethod
    def load(cls) -> Settings:
        api = os.getenv("EVE_API_BASE_URL", "").rstrip("/")
        return cls(
            participant=os.getenv("PARTICIPANT", os.getenv("USER", "local")),
            workshop_name=os.getenv("WORKSHOP_NAME", "local"),
            user_bucket=os.getenv("USER_BUCKET", ""),
            shared_bucket=os.getenv("SHARED_BUCKET", ""),
            eve_api_base_url=api,
            eve_api_key=os.getenv("EVE_API_KEY", ""),
            eve_llm_base_url=f"{api}/v1" if api else "",
            eve_llm_model=os.getenv("EVE_LLM_MODEL", "jsc/alias-eve"),
            eve_mcp_base_url=f"{api}/mcp" if api else "",
            registry_dir=Path(os.getenv("REGISTRY_DIR", Path.home() / "mcp-tool-registry")),
        )

    @property
    def eve_configured(self) -> bool:
        return bool(self.eve_api_base_url and self.eve_api_key)

    def summary(self) -> str:
        rows = [
            ("Participant", self.participant),
            ("Event", self.workshop_name),
            ("CPU", _cpu()),
            ("RAM", _ram()),
            ("GPU", _gpu()),
            ("EVE API", self.eve_api_base_url or "(not set)"),
            ("EVE key", masked(self.eve_api_key)),
            ("EVE model", self.eve_llm_model),
        ]
        width = max(len(k) for k, _ in rows)
        return "\n".join(f"{k:<{width}}  {v}" for k, v in rows)


def _sysctl(name: str) -> str:
    try:
        proc = subprocess.run(
            ["sysctl", "-n", name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _format_bytes(n: int) -> str:
    gib = n / (1024**3)
    if gib >= 1:
        return f"{gib:.1f} GB"
    return f"{n / (1024**2):.0f} MB"


def _cpu() -> str:
    count = os.cpu_count() or 0
    name = ""
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.lower().startswith("model name"):
                name = line.split(":", 1)[1].strip()
                break
    elif sys.platform == "darwin":
        name = _sysctl("machdep.cpu.brand_string")
    if name and count:
        return f"{count} cores, {name}"
    if count:
        return f"{count} cores"
    return name or "(unknown)"


def _ram() -> str:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                return _format_bytes(int(line.split()[1]) * 1024)
    if sys.platform == "darwin":
        raw = _sysctl("hw.memsize")
        if raw.isdigit():
            return _format_bytes(int(raw))
    return "(unknown)"


def _gpu() -> str:
    binary = shutil.which("nvidia-smi")
    if not binary:
        return "none"
    try:
        proc = subprocess.run(
            [binary, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "none"
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or not lines:
        return "none"
    return "; ".join(lines)


settings = Settings.load()
