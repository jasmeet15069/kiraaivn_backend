"""Minimal shared-password auth. Stdlib only (hmac/hashlib), no session
store needed — a token is just a timestamp signed with a server secret, so
verifying it doesn't require looking anything up.

This exists specifically because /api/service-control can stop real
production services (not just Jarvis's own) — every /api/* route except
/api/login and /api/health requires a valid token (see app.py's
before_request hook).
"""
import base64
import hashlib
import hmac
import json
import os
import time

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET") or DASHBOARD_PASSWORD
TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def _b64encode(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).decode().rstrip("=")


def _b64decode(text):
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded)


def _sign(payload_b64):
    return hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()


def check_password(password):
    return bool(DASHBOARD_PASSWORD) and hmac.compare_digest(str(password), DASHBOARD_PASSWORD)


def create_token():
    payload_b64 = _b64encode(json.dumps({"iat": time.time()}).encode())
    sig_b64 = _b64encode(_sign(payload_b64))
    return f"{payload_b64}.{sig_b64}"


def verify_token(token):
    if not token or not SESSION_SECRET:
        return False
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig_b64 = _b64encode(_sign(payload_b64))
        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return False
        payload = json.loads(_b64decode(payload_b64))
        return (time.time() - float(payload["iat"])) < TOKEN_TTL_SECONDS
    except Exception:
        return False
