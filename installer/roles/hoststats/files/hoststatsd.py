#!/usr/bin/env python3
"""pentrain-hoststats — stdlib-only host telemetry for the /stats page.

Serves GET /stats on :9100 — read-only, LAN-scoped lab service, no auth.
Sources: `sensors -j` (lm-sensors), nvidia-smi when present, amdgpu sysfs
(gpu_busy_percent + hwmon temp). Everything is best-effort: a missing tool or
device yields an empty section, never a 500.
"""
import json
import re
import shutil
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 9100


def _sensors() -> dict:
    if not shutil.which("sensors"):
        return {}
    try:
        out = subprocess.run(["sensors", "-j"], capture_output=True,
                             text=True, timeout=10, check=False)
        return json.loads(out.stdout) if out.returncode == 0 else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _temps_fans(data: dict) -> tuple[list[dict], list[dict]]:
    temps: list[dict] = []
    fans: list[dict] = []
    for chip, features in data.items():
        if not isinstance(features, dict):
            continue
        chipname = str(chip).split("-")[0]
        for fname, fdata in features.items():
            if not isinstance(fdata, dict):
                continue
            for key, val in fdata.items():
                if not key.endswith("_input") or not isinstance(val, (int, float)):
                    continue
                label = f"{chipname}·{fname}"
                if key.startswith("temp"):
                    temps.append({"label": label, "c": round(val, 1)})
                    break  # one reading per feature
                elif key.startswith("fan"):
                    fans.append({"label": label, "rpm": int(val)})
                    break
    return temps, fans


def _gpu_nvidia() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        name, util, temp, mu, mt = (p.strip() for p in out.stdout.splitlines()[0].split(","))
        return {"name": name, "vendor": "nvidia", "util_pct": float(util),
                "temp_c": float(temp), "mem_used_mb": float(mu),
                "mem_total_mb": float(mt)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _gpu_amdgpu() -> dict | None:
    try:
        for card in sorted(Path("/sys/class/drm").iterdir()):
            if not re.fullmatch(r"card\d+", card.name):
                continue
            busy = card / "device" / "gpu_busy_percent"
            if not busy.exists():
                continue
            util = float(busy.read_text().strip())
            temp = None
            for hw in (card / "device" / "hwmon").glob("hwmon*/temp1_input"):
                try:
                    temp = round(int(hw.read_text().strip()) / 1000, 1)
                    break
                except (ValueError, OSError):
                    continue
            return {"name": card.name, "vendor": "amd", "util_pct": util,
                    "temp_c": temp, "mem_used_mb": None, "mem_total_mb": None}
    except (OSError, ValueError):
        return None


class _H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            return self._send(200, {"ok": True})
        if self.path != "/stats":
            return self._send(404, {"error": "not found"})
        temps, fans = _temps_fans(_sensors())
        pkg = next((t["c"] for t in temps
                    if any(k in t["label"] for k in ("Tctl", "Tdie", "Package"))),
                   temps[0]["c"] if temps else None)
        self._send(200, {
            "ts": int(time.time()),
            "cpu": {"package_c": pkg, "temps": temps},
            "gpu": _gpu_nvidia() or _gpu_amdgpu(),
            "fans": fans,
        })

    def log_message(self, *a) -> None:  # quiet — one log line per poll floods journald
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), _H).serve_forever()
