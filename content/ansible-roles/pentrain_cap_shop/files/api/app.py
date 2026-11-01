#!/usr/bin/env python3
"""Nordmarkt order-export API.

Internal service on the shopapp bridge net. Bearer-token auth; the export
endpoint shells out to the legacy `order-report` wrapper and passes user
input straight into the command line — that's the vulnerability.
"""
import os
import subprocess

from flask import Flask, jsonify, request

app = Flask(__name__)
TOKEN = os.environ.get("API_TOKEN", "")


@app.get("/")
def index():
    return jsonify(service="nordmarkt-orders", version="1.4",
                   endpoints=["/api/health", "/api/export"])


@app.get("/api/health")
def health():
    return jsonify(status="ok", db=os.environ.get("DB_HOST", "unset"))


@app.get("/api/export")
def export():
    if request.headers.get("Authorization") != f"Bearer {TOKEN}":
        return jsonify(error="unauthorized"), 401
    since = request.args.get("since", "2024-01-01")
    fmt = request.args.get("fmt", "csv")
    # legacy reporting path: raw query params go into a shell command line
    out = subprocess.getoutput(
        f"/usr/local/bin/order-report --fmt {fmt} --since {since}")
    return app.response_class(out, mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
