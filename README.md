# kiraaivn_backend

Flask API that fronts the Kira AI chat models plus two local llama.cpp
models, gives Jarvis session-scoped memory, file attachments, a sandboxed
code tool, and an MCP connector — all behind one API so the frontend never
talks to any upstream provider directly.

## Endpoints

- `POST /api/chat` — `{ model, messages, session_id, attachments? }` → `{ reply, used_tools }`
- `GET /api/models` — merged list of cloud + local + (auto-discovered) Ollama models
- `GET /api/history?session_id=...` — this session's saved transcript
- `DELETE /api/history?session_id=...` — clear it
- `GET /api/health` — liveness check

## Features

**Attachments** — `attachments: [{name, kind, content, size}]` on a chat
request. `kind: "text"` is inlined into the prompt as a fenced code block;
`kind: "image"` is sent as an `image_url` part to cloud models only (the
local llama.cpp models here are text-only); anything else is noted by name
but not read.

**Memory** — each browser gets a `session_id` (generated client-side,
stored in `localStorage`). The backend persists the full transcript and any
facts Jarvis chooses to save via the `remember` tool in SQLite
(`data/jarvis.db`), scoped strictly per `session_id` — one visitor's
conversation is never visible to another's.

**Tool-calling loop / anti-hallucination** — a small ReAct-style protocol
(see `tools.py`) lets the model call `remember`, `recall`, `run_code`, and
any configured MCP tools by emitting `<tool_call>{...}</tool_call>`,
regardless of whether the underlying provider has native function calling.
The system prompt instructs the model to say "I'm not sure" and use
`recall`/`run_code` rather than guess at facts it can't verify.

**Sandboxed code execution (`run_code`)** — the *only* system access Jarvis
has. Runs Python via `firejail` as a dedicated unprivileged `kirasandbox`
user: no network, no filesystem access outside a throwaway scratch
directory, capped CPU/memory, ~10s timeout, output truncated and logged to
`exec_log`. It cannot reach this VPS's other services, files, or the host
itself.

**MCP connector** — `mcp_client.py` connects to any MCP servers listed in
`mcp_servers.json` (copy from `mcp_servers.example.json`; gitignored, since
a server config can carry paths/tokens) and exposes their tools into the
same tool-calling loop, namespaced `mcp_<server>_<tool>`. Ships with no
servers enabled by default; the example config wires up the reference
filesystem MCP server scoped to the same sandbox directory `run_code` uses.

**System connector (external hosts, NOT this VPS)** — `connectors.json`
(copy from `connectors.example.json`) is meant to let Jarvis run commands
on *other* systems you explicitly register credentials for. This VPS is
deliberately never a valid target. **Execution is currently a stub** —
`tools.system_exec()` returns a "not wired up" message instead of actually
connecting. Wiring it up needs an SSH client library (`paramiko`); the
`pip install paramiko` step was held back by the Claude Code auto-mode
security classifier for explicit human approval rather than run
automatically. To finish this: either run
`/opt/kira-chat-backend/.venv/bin/pip install paramiko` yourself and ask to
have `system_exec` implemented against it, or grant the relevant Bash
permission and ask again.

## Run locally

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in KIRA_API_KEY
.venv/bin/gunicorn -w 2 -b 127.0.0.1:5001 app:app
```

## Deploy

See `kira-chat-backend.service` for the systemd unit used in production
(`/opt/kira-chat-backend`, reverse-proxied by Nginx).
