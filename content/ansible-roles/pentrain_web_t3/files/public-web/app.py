"""NorthBridge public site — intentionally vulnerable URL-preview feature.

The SSRF is the quest: urllib fetches any scheme it supports (http, file).
The backend container 'internal-api' shares this docker network.
"""
from flask import Flask, Response, request
import urllib.request

app = Flask(__name__)

INDEX = """<!doctype html><title>NorthBridge</title>
<h1>NorthBridge Communications</h1>
<p>Press office · Careers · Contact</p>
<p><b>New:</b> try our <a href="/preview?url=https://example.com">link preview</a> tool.</p>
<footer><small>© 2025 NorthBridge</small></footer>"""


@app.get("/")
def index():
    return INDEX


@app.get("/robots.txt")
def robots():
    # breadcrumb: hints at the web container's /srv/app working dir
    return Response("User-agent: *\nDisallow: /srv/app/\n", mimetype="text/plain")


@app.get("/preview")
def preview():
    url = request.args.get("url", "")
    if not url:
        return Response("usage: /preview?url=<url>", status=400)
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return Response(r.read()[:20000],
                            content_type=r.headers.get("content-type", "text/plain"))
    except Exception as e:
        return Response(f"preview fetch failed: {e}", status=502)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
