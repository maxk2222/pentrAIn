#!/usr/bin/env python3
"""pentrain web-t3-jwt-idor api — deliberately vulnerable for training.
Weak HS256 secret, IDOR on /api/users/<id>/export, admin claim gate.
Teaching quest for the mechanics web-t3-exam grades on."""
import functools

import jwt
from flask import Flask, jsonify, request

app = Flask(__name__)
JWT_SECRET = "letmein"  # <-- the vulnerability: dictionary-word secret

USERS = {
    1: {"user": "admin", "role": "admin", "export": "/var/lib/api/user-flag.txt"},
    2: {"user": "auditor", "role": "user", "export": None},
    3: {"user": "intern", "role": "user", "export": None},
}
PASSWORDS = {"auditor": "Audit2024!", "intern": "Intern2024!"}


def require_auth(admin=False):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            token = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            try:
                claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            except Exception:
                return jsonify({"error": "invalid token"}), 401
            if admin and not claims.get("admin"):
                return jsonify({"error": "admin required"}), 403
            request.claims = claims
            return fn(*a, **kw)

        return wrapper

    return deco


@app.post("/api/login")
def login():
    body = request.get_json(silent=True) or {}
    user, pw = body.get("username"), body.get("password")
    if PASSWORDS.get(user) != pw:
        return jsonify({"error": "bad credentials"}), 401
    uid = next(k for k, v in USERS.items() if v["user"] == user)
    token = jwt.encode({"sub": user, "uid": uid, "admin": False}, JWT_SECRET, algorithm="HS256")
    return jsonify({"token": token})


@app.get("/api/users/<int:uid>/export")
@require_auth()
def export(uid):
    # IDOR: no check that claims["uid"] == uid
    rec = USERS.get(uid)
    if not rec:
        return jsonify({"error": "no such user"}), 404
    out = {"user": rec["user"], "role": rec["role"]}
    if rec["export"]:
        try:
            out["export"] = open(rec["export"]).read().strip()
        except OSError:
            out["export"] = None
    return jsonify(out)


@app.get("/api/admin/report")
@require_auth(admin=True)
def report():
    try:
        flag = open("/var/lib/api/admin-flag.txt").read().strip()
    except OSError:
        flag = None
    return jsonify({"quarterly": "on track", "restricted": flag})


@app.get("/")
def index():
    return jsonify({"service": "reporting-api",
                    "demo_account": "auditor / Audit2024!",
                    "endpoints": [
        "POST /api/login", "GET /api/users/<id>/export",
        "GET /api/admin/report"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
