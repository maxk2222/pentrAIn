#!/usr/bin/env python3
"""scr-t2 target API — nonce + PIN auth in front of a secret file.

Flow: GET /api/nonce -> {nonce}; POST /api/auth {nonce, pin} -> {token}
(the pin is a 4-digit code — the trainee's script brute-forces it);
GET /api/secret with Bearer token -> contents of /srv/api/secret.txt.
"""
import hashlib
import secrets
import time

from flask import Flask, jsonify, request

app = Flask(__name__)

PIN = "4217"
_nonces: dict[str, float] = {}
_tokens: dict[str, float] = {}
NONCE_TTL = 120
TOKEN_TTL = 300


def _nonce_ok(n: str) -> bool:
    ts = _nonces.pop(n, None)
    return ts is not None and time.time() - ts < NONCE_TTL


@app.get("/api/nonce")
def nonce():
    n = secrets.token_hex(8)
    _nonces[n] = time.time()
    return jsonify({"nonce": n, "algo": "sha256(nonce + pin)"})


@app.post("/api/auth")
def auth():
    body = request.get_json(silent=True) or {}
    n, pin, proof = body.get("nonce"), str(body.get("pin", "")), body.get("proof")
    if not _nonce_ok(n):
        return jsonify({"error": "bad or expired nonce"}), 401
    expect = hashlib.sha256(f"{n}{pin}".encode()).hexdigest()
    if pin != PIN or proof != expect:
        return jsonify({"error": "invalid pin or proof"}), 403
    tok = secrets.token_hex(16)
    _tokens[tok] = time.time()
    return jsonify({"token": tok, "ttl": TOKEN_TTL})


@app.get("/api/secret")
def secret():
    tok = (request.headers.get("Authorization") or "").removeprefix("Bearer ")
    if not _tokens.get(tok) or time.time() - _tokens[tok] > TOKEN_TTL:
        return jsonify({"error": "unauthorized"}), 401
    return open("/srv/api/secret.txt").read()


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
