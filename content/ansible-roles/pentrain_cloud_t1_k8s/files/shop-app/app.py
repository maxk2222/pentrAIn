#!/usr/bin/env python3
"""shop-app — deliberately debuggable storefront pod (cloud-native lab)."""
import os
import subprocess

from flask import Flask, request

app = Flask(__name__)


@app.get("/")
def index():
    return {
        "service": "northbridge-shop",
        "note": "internal tools moved to /exec — ops only",
        "flags": "/etc/labflags holds the operator seed bundle",
    }


@app.get("/exec")
def exec_():
    # classic debug endpoint left enabled in prod — command injection as a
    # service. THIS is the intended entry point of the lab.
    cmd = request.args.get("cmd", "id")
    try:
        out = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True,
                             text=True, timeout=15)
        return {"out": out.stdout, "err": out.stderr, "code": out.returncode}
    except subprocess.TimeoutExpired:
        return {"err": "timed out", "code": 124}


@app.get("/healthz")
def healthz():
    return {"ok": True}
