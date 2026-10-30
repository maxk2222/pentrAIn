"""Internal admin API — no auth, 'isolated network' was the only control."""
from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/")
def index():
    return jsonify({"service": "internal-api", "version": "0.9.1-internal",
                    "endpoints": ["/", "/admin/flag"]})


@app.get("/admin/flag")
def flag():
    try:
        return open("/srv/api/flag.txt").read()
    except FileNotFoundError:
        return jsonify({"error": "flag not injected yet"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
