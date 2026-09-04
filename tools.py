"""Tool registry + the tiny ReAct-style protocol used to let any of the three
model backends (cloud / local llama.cpp / Ollama) call tools, regardless of
whether that backend has native function-calling support.

The model is instructed (see PROMPT_INSTRUCTIONS) to emit a single line of
the form:
    <tool_call>{"name": "recall", "arguments": {"query": "..."}}</tool_call>
when it wants to use a tool. We parse that out of its raw text reply, run
the tool, feed the result back in, and loop.
"""
import json
import os
import re

import mcp_client
import sandbox
import storage

MAX_TOOL_ITERATIONS = 4

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

CONNECTORS_CONFIG = os.environ.get(
    "JARVIS_CONNECTORS_CONFIG",
    os.path.join(os.path.dirname(__file__), "connectors.json"),
)


def load_connectors():
    if not os.path.exists(CONNECTORS_CONFIG):
        return {}
    try:
        with open(CONNECTORS_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f).get("connectors", {})
    except (OSError, ValueError):
        return {}


def system_exec(connector_name, command):
    # Deliberately not implemented: wiring this up needs an SSH client
    # library, and installing one (paramiko) was blocked by the Claude Code
    # auto-mode security classifier pending explicit human follow-up. See
    # README.md "System connector" section.
    return (
        f"[system connector '{connector_name}' is configured but not active: "
        "SSH execution was not wired up automatically — this needs a manual "
        "follow-up step, see README.md.]"
    )


_MCP_CACHE = None


def discover_mcp_tools(force=False):
    global _MCP_CACHE
    if _MCP_CACHE is None or force:
        _MCP_CACHE = mcp_client.discover_tools()
    return _MCP_CACHE


def build_tool_specs(session_id):
    specs = {
        "remember": {
            "description": "Save a fact worth remembering for later in this conversation "
                            "(e.g. something the user told you about themselves or a preference).",
            "params": '{"key": "<short label>", "value": "<the fact>"}',
            "fn": lambda args: storage.remember(session_id, str(args.get("key", "")), str(args.get("value", ""))),
        },
        "recall": {
            "description": "Look up facts saved earlier in this conversation. Use this before answering "
                            "anything you're not fully certain about, rather than guessing.",
            "params": '{"query": "<search text>"}',
            "fn": lambda args: storage.recall(session_id, str(args.get("query", ""))),
        },
        "run_code": {
            "description": "Run a short Python snippet in an isolated sandbox (no network, no access to "
                            "any real filesystem, ~10s limit). Use it to compute or verify things exactly "
                            "instead of guessing at arithmetic, dates, or logic.",
            "params": '{"code": "<python code>"}',
            "fn": lambda args: sandbox.run_python(str(args.get("code", ""))),
        },
    }

    for name in load_connectors():
        specs[f"system_exec_{name}"] = {
            "description": f"Run a shell command on the external system '{name}'.",
            "params": '{"command": "<shell command>"}',
            "fn": (lambda args, n=name: system_exec(n, str(args.get("command", "")))),
        }

    for server, tool_list in discover_mcp_tools().items():
        for t in tool_list:
            key = f"mcp_{server}_{t['name']}"
            specs[key] = {
                "description": f"[MCP server: {server}] {t['description']}",
                "params": "an object matching this tool's own schema",
                "fn": (lambda args, s=server, tn=t["name"]: mcp_client.call_tool(s, tn, args)),
            }

    return specs


def format_tool_docs(specs):
    if not specs:
        return "(no tools available)"
    lines = []
    for name, spec in specs.items():
        lines.append(f"- {name}({spec['params']}): {spec['description']}")
    return "\n".join(lines)


def _iter_balanced_json_objects(text):
    """Yield every top-level {...} substring, respecting string quoting so
    braces inside a JSON string value don't throw off the depth count."""
    n = len(text)
    i = 0
    while i < n:
        if text[i] == "{":
            depth = 0
            in_string = False
            escape = False
            j = i
            while j < n:
                c = text[j]
                if in_string:
                    if escape:
                        escape = False
                    elif c == "\\":
                        escape = True
                    elif c == '"':
                        in_string = False
                else:
                    if c == '"':
                        in_string = True
                    elif c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            yield text[i:j + 1]
                            break
                j += 1
            i = j + 1
        else:
            i += 1


def parse_tool_call(text):
    """Small local models don't reliably wrap calls in <tool_call> tags, so
    this also falls back to scanning for any bare {"name": ..., "arguments":
    ...} object anywhere in the reply."""
    text = text or ""
    candidates = []
    tag_match = _TOOL_CALL_RE.search(text)
    if tag_match:
        candidates.append(tag_match.group(1))
    candidates.extend(_iter_balanced_json_objects(text))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("name"), str) and "arguments" in payload:
            return payload["name"], payload.get("arguments") or {}
    return None


def strip_tool_call(text):
    text = _TOOL_CALL_RE.sub("", text or "")
    for candidate in list(_iter_balanced_json_objects(text)):
        try:
            payload = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("name"), str) and "arguments" in payload:
            text = text.replace(candidate, "")
    return text.strip()


def run_tool(specs, name, arguments):
    spec = specs.get(name)
    if not spec:
        return f"[unknown tool '{name}']"
    try:
        return str(spec["fn"](arguments))
    except Exception as exc:
        return f"[tool '{name}' failed: {exc}]"
