#!/usr/bin/env python3
"""nordwind inventory API — internal tier service.

Self-contained HS256 JWT (stdlib only) + a diagnostics endpoint that shells
out to ping. Known-bad patterns live here on purpose (pentest range).
"""
import base64
import hashlib
import hmac
import json
import subprocess
import time

import yaml
from flask import Flask, jsonify, request

with open("/srv/api/config.yml") as fh:
    CONF = yaml.safe_load(fh)

APP_SECRET = CONF["app_secret"].encode()
app = Flask(__name__)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _issue(claims: dict) -> str:
    head = _b64(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = _b64(hmac.new(APP_SECRET, f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def _claims(tok: str) -> dict | None:
    try:
        head, body, sig = tok.split(".")
        want = _b64(hmac.new(APP_SECRET, f"{head}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            return None
        claims = json.loads(_b64d(body))
        if claims.get("exp", 0) < time.time():
            return None
        return claims
    except Exception:
        return None


def _auth():
    ah = request.headers.get("Authorization", "")
    return _claims(ah[7:]) if ah.startswith("Bearer ") else None


@app.get("/api/v1/status")
def status():
    return jsonify(service="nordwind-inventory", version="2.1", status="ok")


@app.post("/api/v1/token")
def token():
    user = (request.get_json(silent=True) or {}).get("user") or "viewer"
    return jsonify(token=_issue({"sub": user, "role": "viewer",
                               "iat": int(time.time()), "exp": int(time.time()) + 3600}))


@app.get("/api/v1/items")
def items():
    if not _auth():
        return jsonify(error="unauthorized"), 401
    return jsonify(items=[
        {"sku": "NW-1002", "desc": "pallet wrap", "qty": 4200},
        {"sku": "NW-2210", "desc": "cold-chain sensor", "qty": 63},
        {"sku": "NW-8710", "desc": "dock seal kit", "qty": 12},
    ])


@app.get("/api/v1/admin/diag")
def diag():
    claims = _auth()
    if not claims or claims.get("role") != "admin":
        return jsonify(error="admin required"), 403
    host = request.args.get("host", "127.0.0.1")
    # diagnostic shell-out — the whole reason this endpoint is a finding
    out = subprocess.run(f"ping -c1 -W2 {host}", shell=True,
                         capture_output=True, text=True, timeout=10)
    return jsonify(rc=out.returncode, out=out.stdout + out.stderr)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
