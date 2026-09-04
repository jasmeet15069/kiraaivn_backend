# kiraaivn_backend

Flask API that fronts the Kira AI chat models. Holds the provider API key
server-side and enforces a "Jarvis" identity on the assistant's replies, so
the frontend never talks to the upstream provider directly.

## Endpoints

- `POST /api/chat` — body `{ "model": "kira-mini-1.0", "messages": [...] }`, returns `{ "reply": "..." }`
- `GET /api/health` — liveness check

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
