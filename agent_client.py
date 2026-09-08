"""Laptop-side agent for the Jarvis System Connector.

Run this on the machine you want Jarvis to control. It opens an OUTBOUND
WebSocket connection to your Jarvis backend and holds it open — no inbound
port, no SSH server, no router or firewall changes needed. When Jarvis asks
it to run something, it executes the command locally and sends the result
back over that same connection.

Everything this prints (every command it's asked to run) is your audit log
— keep this window visible, and close it any time to instantly cut Jarvis's
access to this machine.

Usage:
    pip install aiohttp
    python agent_client.py --url wss://kira-chat.167-233-158-179.sslip.io/agent-ws --name my-laptop --token YOUR_TOKEN

(--token can also come from the AGENT_TOKEN environment variable, so it
doesn't sit in your shell history.)
"""
import argparse
import asyncio
import json
import os

import aiohttp

RECONNECT_DELAY_SECONDS = 5
COMMAND_TIMEOUT_SECONDS = 60


async def run_command(command):
    print(f"[agent] running: {command!r}")
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=COMMAND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            return {"output": "[command timed out]", "exit_code": -1}
        return {"output": stdout.decode(errors="replace"), "exit_code": proc.returncode}
    except Exception as exc:
        return {"output": f"[failed to run: {exc}]", "exit_code": -1}


async def main(url, token, name):
    full_url = f"{url}?token={token}&name={name}"
    print(f"[agent] connecting to {url} as '{name}'...")
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(full_url) as ws:
                    print(f"[agent] connected as '{name}' — waiting for commands")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            result = await run_command(data.get("command", ""))
                            result["id"] = data.get("id")
                            await ws.send_json(result)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
        except Exception as exc:
            print(f"[agent] connection error: {exc}")
        print(f"[agent] disconnected, retrying in {RECONNECT_DELAY_SECONDS}s...")
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="wss://your-backend/agent-ws")
    parser.add_argument("--name", required=True, help="a name for this machine, e.g. my-laptop")
    parser.add_argument("--token", default=os.environ.get("AGENT_TOKEN", ""))
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("Pass --token or set the AGENT_TOKEN environment variable.")
    try:
        asyncio.run(main(args.url, args.token, args.name))
    except KeyboardInterrupt:
        print("\n[agent] stopped.")
