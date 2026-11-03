from flask import Flask, request

app = Flask(__name__)
LOG = "/var/log/requests.log"
FLAG_FILE = "/srv/api/flag.txt"


@app.before_request
def log_request():
    # the smuggled request arrives as a SECOND request on the same backend
    # connection — this log is what proves it ever reached us.
    with open(LOG, "a") as f:
        f.write(f"{request.method} {request.path}\n")


@app.get("/")
def index():
    return {
        "service": "northbridge-backend",
        "note": "internal endpoints are edge-filtered; nothing here is public",
    }


@app.post("/track")
def track():
    return {"ok": True}


@app.get("/internal/flag")
def flag():
    try:
        return {"flag": open(FLAG_FILE).read().strip()}
    except OSError:
        return {"error": "flag not provisioned"}, 503


@app.route("/internal/<path:rest>")
def internal(rest):
    return {"internal": rest}
