"""Outbound-only remote execution gateway for the System Connector.

A laptop (or any other machine) runs agent_client.py, which opens a
WebSocket connection OUT to this gateway — no inbound port on the laptop,
no SSH server, no router/firewall changes. The gateway holds that
connection open and relays exec requests from the Flask backend to it.

Runs as its own process (see kira-agent-gateway.service) separate from the
Flask backend's gunicorn workers, since it needs a persistent asyncio event
loop to hold WebSocket connections open — gunicorn's sync workers can't do
that without blocking chat requests.

/agent-ws is the only route Nginx should expose publicly. /exec and
/status are for the Flask backend to call over localhost only.
"""
import asyncio
import json
import os
import time
import uuid

from aiohttp import web, WSMsgType

AGENT_TOKEN = os.environ["AGENT_GATEWAY_TOKEN"]
PORT = int(os.environ.get("AGENT_GATEWAY_PORT", "5002"))
EXEC_TIMEOUT_DEFAULT = 30
EXEC_TIMEOUT_MAX = 120

agents = {}    # name -> {"ws": WebSocketResponse, "connected_at": float}
pending = {}   # request_id -> asyncio.Future


async def agent_ws(request):
    token = request.query.get("token", "")
    name = request.query.get("name", "").strip()
    if token != AGENT_TOKEN or not name:
        return web.Response(status=401, text="unauthorized")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    agents[name] = {"ws": ws, "connected_at": time.time()}
    print(f"[gateway] agent '{name}' connected")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                fut = pending.pop(data.get("id"), None)
                if fut and not fut.done():
                    fut.set_result(data)
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        if agents.get(name, {}).get("ws") is ws:
            del agents[name]
        print(f"[gateway] agent '{name}' disconnected")
    return ws


async def exec_handler(request):
    body = await request.json()
    name = body.get("agent", "")
    command = body.get("command", "")
    timeout = min(float(body.get("timeout", EXEC_TIMEOUT_DEFAULT)), EXEC_TIMEOUT_MAX)

    entry = agents.get(name)
    if not entry:
        return web.json_response({"error": f"agent '{name}' is not connected"}, status=502)

    req_id = uuid.uuid4().hex
    fut = asyncio.get_event_loop().create_future()
    pending[req_id] = fut
    try:
        await entry["ws"].send_json({"id": req_id, "action": "shell", "command": command})
        result = await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        pending.pop(req_id, None)
        return web.json_response({"error": "agent did not respond in time"}, status=504)
    except Exception as exc:
        pending.pop(req_id, None)
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response(result)


async def status_handler(request):
    return web.json_response({name: {"connected_at": info["connected_at"]} for name, info in agents.items()})


app = web.Application()
app.router.add_get("/agent-ws", agent_ws)
app.router.add_post("/exec", exec_handler)
app.router.add_get("/status", status_handler)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=PORT)
