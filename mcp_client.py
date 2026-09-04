"""Minimal synchronous wrapper around the MCP Python SDK.

Servers are configured in mcp_servers.json (gitignored — copy from
mcp_servers.example.json). Each configured server is reconnected fresh for
every call, which is simpler and more robust than holding a long-lived
session across Flask's sync worker processes; MCP tool calls are expected to
be occasional, not hot-path.

If a server is misconfigured or unreachable, it's skipped — one broken
connector never takes down chat.
"""
import asyncio
import json
import os

CONFIG_PATH = os.environ.get(
    "JARVIS_MCP_CONFIG",
    os.path.join(os.path.dirname(__file__), "mcp_servers.json"),
)


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return []
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("servers", [])
    except (OSError, ValueError):
        return []


async def _list_tools_async(server_cfg):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=server_cfg["command"],
        args=server_cfg.get("args", []),
        env={**os.environ, **server_cfg.get("env", {})},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {"name": t.name, "description": t.description or ""}
                for t in result.tools
            ]


async def _call_tool_async(server_cfg, tool_name, arguments):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=server_cfg["command"],
        args=server_cfg.get("args", []),
        env={**os.environ, **server_cfg.get("env", {})},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            parts = []
            for block in result.content:
                text = getattr(block, "text", None)
                parts.append(text if text is not None else str(block))
            return "\n".join(parts) if parts else "(no output)"


def discover_tools(timeout=8):
    """Best-effort: {server_name: [{name, description}, ...]}. Never raises."""
    discovered = {}
    for server_cfg in _load_config():
        name = server_cfg.get("name")
        if not name:
            continue
        try:
            tools = asyncio.run(asyncio.wait_for(_list_tools_async(server_cfg), timeout))
            discovered[name] = tools
        except Exception:
            continue
    return discovered


def call_tool(server_name, tool_name, arguments, timeout=30):
    for server_cfg in _load_config():
        if server_cfg.get("name") == server_name:
            try:
                return asyncio.run(
                    asyncio.wait_for(_call_tool_async(server_cfg, tool_name, arguments), timeout)
                )
            except Exception as exc:
                return f"[MCP error: {exc}]"
    return f"[MCP server '{server_name}' is not configured]"
