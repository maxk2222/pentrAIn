#!/usr/bin/env python3
"""edge01 public-web — marketing site + URL preview fetcher (SSRF lab)."""
import urllib.request

from flask import Flask, request

app = Flask(__name__)


@app.get("/")
def index():
    return ("<!doctype html><title>NorthBridge</title><h1>NorthBridge "
            "Communications</h1><p>Press office · Careers · "
            "<a href=\"/preview?url=https://example.com\">URL preview</a>"
            "</p>")


@app.get("/preview")
def preview():
    url = request.args.get("url", "")
    if not url:
        return {"error": "url param required"}, 400
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return r.read(8192).decode("utf-8", "replace")
    except Exception as e:  # surface errors — it's a preview/debug feature
        return {"error": str(e)[:200]}


@app.get("/healthz")
def healthz():
    return {"ok": True}
