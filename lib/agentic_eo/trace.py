"""Notebook view of a ReAct trace.

Adapted from ``visualize_agent_trace`` in the phi-innovation tour
(https://github.com/eve-esa/phinnovation, ``Agentic_EVE.ipynb``). Steps use the
same shape: ``node`` is ``agent`` or ``tools``, plus ``latency_s``, ``content``,
and ``tool_calls`` / ``name``.
"""

from __future__ import annotations

import ast as _ast
import html
import json
import re
from typing import Any

_JSON_TOKEN_RE = re.compile(
    r'("(?:[^"\\]|\\.)*")(\s*:)'
    r'|("(?:[^"\\]|\\.)*")'
    r'|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    r'|\b(true|false|null)\b'
)

_STEP_STYLES = {
    "agent": {
        "bg": "#f5f3ff",
        "rail": "#7c3aed",
        "pill_bg": "#ede9fe",
        "pill_fg": "#5b21b6",
        "title": "Agent step",
        "sub": "Plans the next action or writes the final reply.",
        "gantt": "#7c3aed",
    },
    "tools": {
        "bg": "#ecfeff",
        "rail": "#0891b2",
        "pill_bg": "#cffafe",
        "pill_fg": "#155e75",
        "title": "Tool execution",
        "sub": "Runs one tool and returns its payload.",
        "gantt": "#0891b2",
    },
}
_DEFAULT_STYLE = {
    "bg": "#f8fafc",
    "rail": "#64748b",
    "pill_bg": "#f1f5f9",
    "pill_fg": "#475569",
    "title": "Step",
    "sub": "",
    "gantt": "#94a3b8",
}

_PRE = (
    "margin:0;padding:0.45rem 0.65rem;background:#f8fafc;border:1px solid #e2e8f0;"
    "border-radius:0 6px 6px 0;font-size:0.7rem;line-height:1.5;white-space:pre-wrap;"
    "word-break:break-word;color:#334155;font-family:ui-monospace,'SFMono-Regular',Consolas,monospace"
)
_LBL = (
    "font-size:0.65rem;text-transform:uppercase;letter-spacing:0.07em;color:#64748b;"
    "display:block;margin:0.55rem 0 0.2rem"
)
_CODE = (
    "background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:0.78rem;color:#1e293b;"
    "font-family:ui-monospace,'SFMono-Regular',Consolas,monospace"
)


def _as_payload(result: Any) -> dict:
    if isinstance(result, dict):
        return result
    return {
        "query": getattr(result, "query", ""),
        "answer": getattr(result, "answer", str(result)),
        "trace": list(getattr(result, "trace", []) or []),
        "metadata": getattr(result, "metadata", None) or {},
    }


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _highlight_json(text: str) -> str:
    """HTML with inline-style JSON colouring (no style block)."""
    out, last = [], 0
    for match in _JSON_TOKEN_RE.finditer(text):
        out.append(html.escape(text[last:match.start()]))
        last = match.end()
        key, sep, string, number, keyword = match.group(1), match.group(2), match.group(3), match.group(4), match.group(5)
        if key:
            out.append(
                f'<span style="color:#6d28d9;font-weight:600">{html.escape(key)}</span>'
                f'<span style="color:#475569">{html.escape(sep)}</span>'
            )
        elif string:
            out.append(f'<span style="color:#15803d">{html.escape(string)}</span>')
        elif number:
            out.append(f'<span style="color:#c2410c">{html.escape(number)}</span>')
        elif keyword:
            out.append(f'<span style="color:#0e7490;font-weight:600">{html.escape(keyword)}</span>')
    out.append(html.escape(text[last:]))
    return "".join(out)


def _extract_tool_output(raw: Any) -> tuple[str, bool]:
    """Unwrap a tool output into ``(display_text, is_json)``."""
    if raw is None:
        return "", False

    if isinstance(raw, str):
        stripped = raw.strip()
        try:
            raw = _ast.literal_eval(stripped)
        except Exception:
            try:
                raw = json.loads(stripped)
            except Exception:
                if stripped and stripped[0] in ("{", "["):
                    try:
                        return json.dumps(json.loads(stripped), indent=2, ensure_ascii=False), True
                    except Exception:
                        pass
                return raw, False

    if (
        isinstance(raw, list)
        and raw
        and all(isinstance(item, dict) and item.get("type") == "text" for item in raw)
    ):
        joined = "\n".join(item.get("text", "") for item in raw)
        try:
            return json.dumps(json.loads(joined), indent=2, ensure_ascii=False), True
        except Exception:
            return joined, False

    try:
        return json.dumps(raw, indent=2, ensure_ascii=False, default=str), True
    except Exception:
        return str(raw), False


def _pair_tool_inputs(trace: list[dict[str, Any]]) -> dict[int, Any]:
    """Map each tools-step index to the args from the preceding agent tool_calls queue."""
    queue: list[tuple[Any, Any]] = []
    paired: dict[int, Any] = {}
    for index, step in enumerate(trace):
        node = (step.get("node") or "").lower()
        if node == "agent":
            for call in step.get("tool_calls") or []:
                queue.append((call.get("name"), call.get("args")))
        elif node == "tools":
            name = step.get("name")
            args = None
            for queued_at, (queued_name, queued_args) in enumerate(queue):
                if queued_name == name:
                    args = queued_args
                    queue.pop(queued_at)
                    break
            if args is None and queue:
                args = queue.pop(0)[1]
            paired[index] = args
    return paired


def _print_trace(payload: dict) -> None:
    """Plain-text trace for when the notebook display is unavailable."""
    trace = payload.get("trace") or []
    print(f"Query: {payload.get('query', '')}")
    if not trace:
        print("(no trace)")
        return
    inputs = _pair_tool_inputs(trace)
    for index, step in enumerate(trace):
        node = (step.get("node") or "step").lower()
        latency = float(step.get("latency_s") or 0)
        if node == "tools":
            print(f"\n[{index + 1}] tool {step.get('name')} ({latency:.2f}s)")
            if inputs.get(index) is not None:
                print("  in:", json.dumps(inputs[index], default=str)[:500])
            print("  out:", str(step.get("content") or "")[:500])
        else:
            calls = step.get("tool_calls") or []
            names = ", ".join(call.get("name", "?") for call in calls) or "final answer"
            print(f"\n[{index + 1}] agent ({latency:.2f}s) → {names}")
            content = (step.get("content") or "").strip()
            if content and not calls:
                print(content[:800])
    answer = payload.get("answer") or ""
    if answer:
        print("\nAnswer:\n" + answer)


def _render_html(payload: dict) -> str:
    trace = payload.get("trace") or []
    query = payload.get("query", "")
    meta = payload.get("metadata") or {}
    latencies = meta.get("latencies") or {}
    total = float(latencies.get("total_latency") or 0) or sum(
        float(step.get("latency_s") or 0) for step in trace
    ) or 1e-9

    tool_inputs = _pair_tool_inputs(trace)
    gantt_segs, cursor = [], 0.0
    for step in trace:
        latency = float(step.get("latency_s") or 0)
        left = 100 * cursor / total
        width = max(0.6, 100 * latency / total)
        style = _STEP_STYLES.get((step.get("node") or "").lower(), _DEFAULT_STYLE)
        name = step.get("name") or ((step.get("tool_calls") or [{}])[0].get("name")) or step.get("node", "?")
        tip = _escape(f"{name} · {latency:.1f}s")
        gantt_segs.append(
            f'<div title="{tip}" style="position:absolute;top:4px;bottom:4px;'
            f'left:{left:.2f}%;width:{width:.2f}%;background:{style["gantt"]};'
            f'border-radius:5px;opacity:0.8"></div>'
        )
        cursor += latency

    gantt_html = (
        '<div style="display:flex;justify-content:space-between;font-size:0.7rem;color:#94a3b8;margin-bottom:0.2rem">'
        f"<span>Timeline (by step latency)</span><span>{total:.1f}s total</span></div>"
        '<div style="position:relative;height:26px;background:#f1f5f9;border-radius:7px;'
        'border:1px solid #e2e8f0;overflow:hidden;margin-bottom:1rem">'
        + "".join(gantt_segs)
        + "</div>"
    )

    cards, cumulative = [], 0.0
    for index, step in enumerate(trace):
        node = (step.get("node") or "step").lower()
        style = _STEP_STYLES.get(node, _DEFAULT_STYLE)
        latency = float(step.get("latency_s") or 0)
        cumulative += latency
        role = _escape(step.get("role", ""))
        body: list[str] = []

        if node == "agent":
            calls = step.get("tool_calls") or []
            if calls:
                names = ", ".join(
                    f'<code style="{_CODE}">{_escape(call.get("name", "?"))}</code>' for call in calls
                )
                body.append(
                    f'<p style="margin:0.25rem 0;font-size:0.81rem;color:#475569">Requesting tool(s): {names}</p>'
                )
            content = (step.get("content") or "").strip()
            if content:
                body.append(
                    f'<details style="margin-top:0.4rem"><summary style="cursor:pointer;'
                    f'font-size:0.78rem;color:#6d28d9">Assistant message ({len(content)} chars)</summary>'
                    f'<pre style="{_PRE};margin-top:0.3rem;border-left:3px solid #a78bfa">{_escape(content)}</pre>'
                    f"</details>"
                )
            if not body:
                body.append('<p style="margin:0.2rem 0;font-size:0.81rem;color:#94a3b8">Deciding next action…</p>')
        elif node == "tools":
            tool_name = _escape(step.get("name", "tool"))
            body.append(
                f'<p style="margin:0 0 0.3rem;font-size:0.84rem;color:#1e293b">Tool: '
                f'<code style="background:#cffafe;color:#155e75;padding:2px 8px;border-radius:5px;'
                f'font-size:0.8rem;font-family:ui-monospace,monospace">{tool_name}</code></p>'
            )
            incoming = tool_inputs.get(index)
            if incoming is not None:
                try:
                    incoming_text = json.dumps(incoming, indent=2, ensure_ascii=False)
                except (TypeError, ValueError):
                    incoming_text = str(incoming)
                body.append(
                    f'<span style="{_LBL}">Input — arguments passed to the tool</span>'
                    f'<pre style="{_PRE};border-left:3px solid #7c3aed">{_escape(incoming_text)}</pre>'
                )
            output_text, is_json = _extract_tool_output(step.get("content"))
            output_body = _highlight_json(output_text) if is_json else _escape(output_text)
            body.append(
                f'<span style="{_LBL}">Output — value returned to the model</span>'
                f'<pre style="{_PRE};border-left:3px solid #0891b2">{output_body}</pre>'
            )
        else:
            body.append(f'<pre style="{_PRE}">{_escape(json.dumps(step, indent=2, default=str))}</pre>')

        role_html = f'<span style="font-size:0.74rem;color:#64748b">{role}</span>' if role else ""
        cards.append(
            f'<div style="display:flex;background:{style["bg"]};border-radius:10px;overflow:hidden;'
            f'border:1px solid #e2e8f0;margin-bottom:0.6rem">'
            f'<div style="width:5px;background:{style["rail"]};flex-shrink:0"></div>'
            f'<div style="flex:1;padding:0.65rem 0.9rem 0.75rem;min-width:0">'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.4rem;margin-bottom:0.15rem">'
            f'<span style="font-size:0.63rem;text-transform:uppercase;letter-spacing:0.08em;color:#94a3b8;font-weight:600">Step {index + 1}</span>'
            f'<span style="font-size:0.66rem;font-weight:600;padding:0.1rem 0.45rem;border-radius:999px;'
            f'border:1px solid {style["rail"]};background:{style["pill_bg"]};color:{style["pill_fg"]};'
            f'text-transform:uppercase;letter-spacing:0.04em">{_escape(node)}</span>'
            f"{role_html}"
            f'<span style="margin-left:auto;font-weight:700;color:#b45309;font-size:0.8rem">{latency:.2f}s</span>'
            f"</div>"
            f'<div style="font-size:0.93rem;font-weight:600;color:#1e293b;margin:0 0 0.1rem">{style["title"]}</div>'
            f'<div style="font-size:0.77rem;color:#64748b;margin-bottom:0.4rem">{style["sub"]}</div>'
            + "".join(body)
            + f'<div style="margin-top:0.4rem;font-size:0.67rem;color:#94a3b8;border-top:1px dashed #e2e8f0;padding-top:0.3rem">'
            f"≈ {cumulative:.2f}s elapsed in trace</div></div></div>"
        )

    legend = '<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:0.75rem">'
    for label, style in _STEP_STYLES.items():
        legend += (
            f'<span style="display:inline-flex;align-items:center;gap:0.3rem;font-size:0.72rem;color:#475569">'
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:{style["rail"]}"></span>'
            f"{label}</span>"
        )
    legend += "</div>"

    return (
        '<div style="font-family:ui-sans-serif,system-ui,-apple-system,\'Segoe UI\',Roboto,Helvetica,Arial;'
        "background:#ffffff;color:#1e293b;border-radius:12px;padding:1.1rem 1.4rem 1.3rem;"
        'margin:0.5rem 0 1rem;border:1px solid #e2e8f0;box-shadow:0 1px 6px rgba(0,0,0,0.06)">'
        '<div style="font-size:1.05rem;font-weight:700;color:#1e293b;margin-bottom:0.2rem">Agent execution trace</div>'
        f'<p style="margin:0 0 0.85rem;font-size:0.84rem;color:#64748b">'
        f'<strong style="color:#1e293b">Query</strong> — {_escape(query)}</p>'
        + legend
        + gantt_html
        + "".join(cards)
        + "</div>"
    )


def show_trace(result: Any) -> None:
    """Render ``result`` (an object or dict with a ``trace`` list).

    In a notebook this is the timeline from the phi-innovation tour. Outside one, it prints the same steps.
    """
    payload = _as_payload(result)
    trace = payload.get("trace") or []
    try:
        from IPython.display import HTML, display
    except ImportError:
        _print_trace(payload)
        return
    if not trace and payload.get("answer"):
        trace = [{
            "node": "agent",
            "role": "assistant",
            "latency_s": 0.0,
            "content": payload.get("answer") or "",
            "tool_calls": [],
        }]
        payload = {**payload, "trace": trace}
    if not trace:
        display(HTML("<p><em>No trace in this result.</em></p>"))
        return
    display(HTML(_render_html(payload)))
