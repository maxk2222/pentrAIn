#!/usr/bin/env python3
"""pentrAIn docs media capture — screenshots + walkthrough GIFs of the real UI.

Drives the dev stack (MockProvider) with Playwright, seeds realistic state over
the REST API (sessions, flags, coach messages) and records PNG screenshots plus
frame sequences that are stitched into animated GIFs with Pillow — no ffmpeg.

Prereqs:
    python -m venv docs/media/.venv && docs/media/.venv/bin/pip install -r docs/media/requirements.txt
    docs/media/.venv/bin/python -m playwright install chromium

    # dedicated capture stack (isolated from any running dev instance):
    PENTRAIN_ENGINE_MODE=mock \
    PENTRAIN_CONTENT_DIR=$PWD/content/packs \
    PENTRAIN_DATABASE_URL=sqlite+aiosqlite:////tmp/pentrain-docs.db \
    PENTRAIN_APP_SECRET=docs-capture-secret \
    PENTRAIN_COACH_SERVICE_TOKEN=docs-coach-token \
      backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8010
    cd frontend && npx vite --config vite.docs.config.ts   # serves :5199

Usage:
    capture.py shots --app http://localhost:5199 --api http://localhost:8010
    capture.py gif all --app http://localhost:5199 --api http://localhost:8010
    capture.py gif quest-start …   # a single GIF
    capture.py seed …              # only (re)create the demo session + chat state

    Defaults: --app http://localhost:5173, --api http://localhost:8000
    (plain `make dev` layout). See docs/media/README.md for details.
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, BrowserContext
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
QUEST = "linux-t1-first-foothold"


# ---------------------------------------------------------------- api helpers

class Api:
    def __init__(self, base: str, password: str, coach_token: str):
        self.base = base.rstrip("/")
        self.password = password
        self.coach_token = coach_token
        self.token: str | None = None

    def req(self, method: str, path: str, body: dict | None = None,
            *, coach: bool = False, raw: bool = False):
        headers = {}
        if coach:
            headers["Authorization"] = f"Bearer {self.coach_token}"
        elif self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data,
                                   headers=headers, method=method)
        try:
            with urllib.request.urlopen(r, timeout=30) as res:
                payload = res.read()
                return payload if raw else json.loads(payload or b"null")
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from e

    def login(self) -> None:
        out = self.req("POST", "/api/auth/login", {"password": self.password})
        self.token = out["token"]

    def setup_complete(self) -> None:
        """Finish the wizard headlessly — idempotent (password is re-set)."""
        st = self.req("GET", "/api/setup/status")
        if st.get("completed"):
            return
        self.req("POST", "/api/setup/complete", {"updates": {
            "admin_password": self.password,
            "engine.mode": "mock",
            "llm.base_url": "http://llm.home.lab:1234/v1",
            "llm.model": "qwen3-30b-a3b-uncensored",
            "llm.vision_model": "qwen2.5-vl-7b",
            "llm.reasoning": True,
            "llm.reasoning_effort": "medium",
            "llm.daily_token_budget": 2000000,
            "coach.enabled": True,
            "coach.default_autonomy": 2,
            "coach.verbosity": "normal",
            "resources.max_ram_gb": 48,
            "resources.max_vcpus": 16,
            "resources.max_disk_gb": 500,
        }})

    def active_session(self) -> dict | None:
        return self.req("GET", "/api/sessions/active")

    def start_session(self, quest_id: str = QUEST, autonomy: int = 2) -> dict:
        s = self.active_session()
        if s:
            self.req("POST", f"/api/sessions/{s['id']}/abort")
            for _ in range(60):
                if not self.active_session():
                    break
                time.sleep(0.5)
        return self.req("POST", "/api/sessions",
                        {"quest_id": quest_id, "autonomy_level": autonomy})

    def wait_state(self, sid: int, want: str, timeout: float = 60) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout:
            s = self.req("GET", f"/api/sessions/{sid}")
            if s["state"] == want:
                return s
            if s["state"] in ("failed", "aborted"):
                raise RuntimeError(f"session {sid} -> {s['state']}: {s.get('error')}")
            time.sleep(0.4)
        raise RuntimeError(f"session {sid} never reached {want}")

    def coach_msg(self, sid: int, content: str, kind: str = "chat",
                  meta: dict | None = None) -> None:
        self.req("POST", "/api/coach/message",
                 {"session_id": sid, "kind": kind,
                  "content": content, "meta": meta or {}}, coach=True)

    def coach_stream(self, sid: int, draft_id: str, content: str,
                     *, reasoning: str = "", done: bool = False) -> None:
        self.req("POST", "/api/coach/stream",
                 {"session_id": sid, "draft_id": draft_id, "content": content,
                  "reasoning": reasoning, "done": done, "kind": "chat"}, coach=True)

    def coach_suggest(self, sid: int, command: str, why: str) -> None:
        self.req("POST", "/api/coach/suggest",
                 {"session_id": sid, "command": command, "why": why}, coach=True)

    def user_msg(self, sid: int, content: str) -> None:
        self.req("POST", f"/api/sessions/{sid}/chat", {"content": content})


def expected_flags(db_path: str, sid: int) -> dict[str, str]:
    """flag_key -> secret straight from sqlite (mock mode never writes guests)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "select flag_key, secret from expected_flags where session_id=?",
            (sid,)).fetchall()
        return dict(rows)
    finally:
        con.close()


# ------------------------------------------------------------ browser helpers

def shot(page: Page, path: Path, *, full: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(350)
    page.screenshot(path=str(path), full_page=full)
    print(f"  -> {path.relative_to(ROOT)}")


def ui_login(page: Page, app: str, password: str) -> None:
    page.goto(f"{app}/login", wait_until="networkidle")
    page.fill('input[type="password"]', password)
    page.click('button:has-text("Sign in"), button[type="submit"], form button')
    page.wait_for_function("() => !!localStorage.getItem('pentrain_token')", timeout=8000)
    page.wait_for_load_state("networkidle")


def dismiss_confirm(page: Page) -> None:
    """Accept any window.confirm the UI fires (autonomy 4, resets, abort)."""
    page.on("dialog", lambda d: d.accept())


def confirm_lazy(page: Page) -> None:
    """Confirm the 'Assistance ahead' lazy-modal when it appears."""
    btn = page.locator('button:has-text("lazy cunt")')
    if btn.count():
        btn.first.click()
        page.wait_for_timeout(400)


def open_chat_panel(page: Page) -> None:
    """Expand the coach panel; confirm the assistance lazy-modal if shown."""
    page.click('button[title="Coach panel"]')
    page.wait_for_timeout(400)
    confirm_lazy(page)


class Recorder:
    """Grabs viewport frames on demand; stitches them into an animated GIF."""

    def __init__(self, page: Page):
        self.page = page
        self.frames: list[Image.Image] = []

    def frame(self, hold_ms: int = 0) -> None:
        png = self.page.screenshot(type="png")
        img = Image.open(io.BytesIO(png)).convert("RGB")
        self.frames.append(img)
        if hold_ms:
            self.page.wait_for_timeout(hold_ms)

    def hold(self, ms: int, fps: int = 5) -> None:
        """Keep recording for ms (animation stays alive in the GIF)."""
        step = max(120, int(1000 / fps))
        elapsed = 0
        while elapsed < ms:
            self.frame()
            self.page.wait_for_timeout(step)
            elapsed += step

    def save(self, path: Path, frame_ms: int = 260) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.frames:
            return
        frames = [f.quantize(colors=255, method=Image.MEDIANCUT)
                  for f in self.frames]
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=frame_ms, loop=0, optimize=True)
        print(f"  -> {path.relative_to(ROOT)}  ({len(frames)} frames, "
              f"{path.stat().st_size // 1024} KB)")


# ------------------------------------------------------------- demo scenarios

COACH_WELCOME = (
    "Welcome to **First Foothold**! Your target is `target01` in an isolated "
    "range `/24`. I'll watch your command stream and chime in when you're "
    "stuck — flags are worth 300 pts base.\n\n"
    "Suggested first move: enumerate services before touching SSH.")
COACH_NUDGE = (
    "**Nudge — recon.** The SSH banner on this box leaks more than a version "
    "string. Connect with *any* username and read what it greets you with.")
COACH_REPORT = (
    "Executed (your confirmation): `nmap -sV -sC target01`\n"
    "```\nPORT   STATE SERVICE VERSION\n"
    "22/tcp open  ssh     OpenSSH 9.2p1 Debian 2\n"
    "80/tcp open  http    Apache httpd 2.4.62\n```\n"
    "*(typed live in the `pentrain-coach` tmux)*")
COACH_FLAG_ACK = "**user-flag captured** — 100 pts. `/root/root.txt` is the remaining objective. `sudo -l` is worth a look."


def seed_chat(api: Api, sid: int) -> None:
    api.coach_msg(sid, COACH_WELCOME)
    api.user_msg(sid, "first time on this box — where should I start?")
    api.coach_msg(sid, COACH_NUDGE, kind="hint")
    api.coach_suggest(sid, "nmap -sV -sC target01",
                      "Fingerprint services before touching SSH.")
    api.coach_msg(sid, COACH_REPORT, kind="action_report")


# ------------------------------------------------------------------ shots

def cmd_shots(args, api: Api) -> None:
    out = ASSETS / "screenshots"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx: BrowserContext = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=2, color_scheme="dark")
        page = ctx.new_page()
        dismiss_confirm(page)

        # --- setup wizard (pre-auth screen, only while unconfigured) ---
        page.goto(f"{args.app}/setup", wait_until="networkidle")
        shot(page, out / "01-setup.png", full=True)

        # --- login ---
        page.goto(f"{args.app}/login", wait_until="networkidle")
        shot(page, out / "02-login.png")
        ui_login(page, args.app, args.password)

        # --- dashboard ---
        page.goto(f"{args.app}/", wait_until="networkidle")
        page.wait_for_timeout(600)
        shot(page, out / "03-dashboard.png")

        # --- library ---
        page.goto(f"{args.app}/library", wait_until="networkidle")
        page.wait_for_timeout(600)
        shot(page, out / "04-library.png", full=True)

        # --- quest detail ---
        page.goto(f"{args.app}/quests/{QUEST}", wait_until="networkidle")
        page.wait_for_timeout(600)
        shot(page, out / "05-quest-detail.png")

        # --- session: fresh deploy -> ready -> active workspace ---
        s = api.start_session()
        sid = s["id"]
        api.wait_state(sid, "ready")
        seed_chat(api, sid)
        page.goto(f"{args.app}/session/{sid}", wait_until="networkidle")
        page.wait_for_timeout(800)
        shot(page, out / "06-session-ready.png")

        # activate + open panels (progress + chat)
        page.click('button:has-text("Start hacking")')
        page.wait_for_timeout(800)
        open_chat_panel(page)
        page.wait_for_timeout(800)
        shot(page, out / "07-session-workspace.png")

        # sheet panel as well (spoiler-free cheatsheet)
        page.click('button[title="Reference sheet"]')
        page.wait_for_timeout(300)
        confirm_lazy(page)
        page.wait_for_timeout(600)
        shot(page, out / "08-session-panels.png")

        # flag submit via UI
        flags = expected_flags(args.db, sid)
        if flags:
            page.click('button[title="Reference sheet"]')  # close sheet
            page.wait_for_timeout(300)
            box = page.locator('input[placeholder*="pentrAIn"]').first
            box.fill(next(iter(flags.values())))
            box.press("Enter")
            page.wait_for_timeout(800)
            shot(page, out / "09-session-flag.png")

        # --- leaderboard ---
        page.goto(f"{args.app}/leaderboard", wait_until="networkidle")
        page.wait_for_timeout(600)
        shot(page, out / "10-leaderboard.png", full=True)

        # --- stats ---
        page.goto(f"{args.app}/stats", wait_until="networkidle")
        page.wait_for_timeout(900)
        shot(page, out / "11-stats.png", full=True)

        # --- settings ---
        page.goto(f"{args.app}/settings", wait_until="networkidle")
        page.wait_for_timeout(800)
        shot(page, out / "12-settings.png", full=True)

        browser.close()


# ------------------------------------------------------------------ gifs

def gif_quest_start(args, api: Api) -> None:
    """Library -> quest detail -> deploy -> ready -> activate -> console."""
    out = ASSETS / "gifs"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  color_scheme="dark")
        page = ctx.new_page()
        dismiss_confirm(page)
        rec = Recorder(page)

        ui_login(page, args.app, args.password)
        page.goto(f"{args.app}/library", wait_until="networkidle")
        rec.hold(900)
        page.goto(f"{args.app}/quests/{QUEST}", wait_until="networkidle")
        rec.hold(900)

        s = api.start_session()
        sid = s["id"]
        page.goto(f"{args.app}/session/{sid}", wait_until="domcontentloaded")
        rec.hold(1200)                                   # deploying / log
        api.wait_state(sid, "ready")
        page.wait_for_timeout(600)
        rec.hold(1000)                                   # ready state
        page.click('button:has-text("Start hacking")')
        rec.hold(1400)                                   # console connects
        rec.save(out / "quest-start.gif")
        browser.close()


def gif_coach_chat(args, api: Api) -> None:
    """Open coach panel -> user asks -> streamed answer -> suggestion -> run."""
    out = ASSETS / "gifs"
    sid = _ready_session(api)
    api.coach_msg(sid, COACH_WELCOME)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  color_scheme="dark")
        page = ctx.new_page()
        dismiss_confirm(page)
        rec = Recorder(page)

        ui_login(page, args.app, args.password)
        page.goto(f"{args.app}/session/{sid}", wait_until="networkidle")
        rec.hold(700)
        open_chat_panel(page)
        rec.hold(700)

        api.user_msg(sid, "how should I approach this target?")
        page.wait_for_timeout(400)
        draft = "The SSH banner usually leaks a hint. Enumerate first, then connect with any username and read the greeting — weak credentials were leaked in the briefing."
        buf = ""
        for chunk in [draft[i:i + 14] for i in range(0, len(draft), 14)]:
            buf += chunk
            api.coach_stream(sid, "d1", buf,
                             reasoning="evaluating enumeration depth")
            rec.frame(hold_ms=90)
        api.coach_stream(sid, "d1", draft, done=True)
        api.coach_msg(sid, draft)
        api.coach_suggest(sid, "ssh student@target01",
                          "Try the leaked creds from the briefing.")
        rec.hold(1600)
        # confirm the suggestion chip if rendered
        if page.locator('button:has-text("Run"), '
                        'button:has-text("Confirm"), '
                        'button:has-text("Accept")').count():
            page.locator('button:has-text("Run"), '
                         'button:has-text("Confirm"), '
                         'button:has-text("Accept")').first.click()
            api.coach_msg(sid, COACH_REPORT, kind="action_report")
            rec.hold(1600)
        rec.save(out / "coach-chat.gif")
        browser.close()


def gif_flag_solve(args, api: Api) -> None:
    """Type a flag -> submit -> success -> second flag -> quest solved."""
    out = ASSETS / "gifs"
    sid = _ready_session(api)
    flags = expected_flags(args.db, sid)
    if len(flags) < 2:
        raise RuntimeError("need 2 expected flags — seed the session first")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  color_scheme="dark")
        page = ctx.new_page()
        dismiss_confirm(page)
        rec = Recorder(page)

        ui_login(page, args.app, args.password)
        page.goto(f"{args.app}/session/{sid}", wait_until="networkidle")
        rec.hold(800)
        box = page.locator('input[placeholder*="pentrAIn"]').first
        vals = list(flags.values())
        box.type(vals[0], delay=40)
        rec.frame()
        box.press("Enter")
        api.coach_msg(sid, COACH_FLAG_ACK, kind="chat")
        rec.hold(1800)
        box = page.locator('input[placeholder*="pentrAIn"]').first
        box.type(vals[1], delay=40)
        rec.frame()
        box.press("Enter")
        rec.hold(2200)                                   # solved state lands
        rec.save(out / "flag-solve.gif")
        browser.close()


def gif_panels(args, api: Api) -> None:
    """Toggle the side panels: progress -> sheet -> notes -> chat."""
    out = ASSETS / "gifs"
    sid = _ready_session(api)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  color_scheme="dark")
        page = ctx.new_page()
        dismiss_confirm(page)
        rec = Recorder(page)
        ui_login(page, args.app, args.password)
        page.goto(f"{args.app}/session/{sid}", wait_until="networkidle")
        rec.hold(700)
        open_chat_panel(page)
        rec.hold(900)
        page.click('button[title="Reference sheet"]')
        page.wait_for_timeout(400)
        confirm_lazy(page)
        rec.hold(1000)
        page.click('button[title="Reference sheet"]')
        page.click('button[title="Progress"]')
        page.wait_for_timeout(400)
        rec.hold(800)
        rec.save(out / "workspace-panels.gif")
        browser.close()


def gif_internet(args, api: Api) -> None:
    """Toggle the Kali WAN uplink from the session toolbar."""
    out = ASSETS / "gifs"
    sid = _ready_session(api)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  color_scheme="dark")
        page = ctx.new_page()
        dismiss_confirm(page)
        rec = Recorder(page)
        ui_login(page, args.app, args.password)
        page.goto(f"{args.app}/session/{sid}", wait_until="networkidle")
        rec.hold(700)
        page.click('button[title*="Kali internet"]')
        rec.hold(1500)
        page.click('button[title*="Kali internet"]')
        rec.hold(1200)
        rec.save(out / "internet-toggle.gif")
        browser.close()


def _ready_session(api: Api) -> int:
    """Return a session id that is ACTIVE (deploy + activate as needed)."""
    s = api.active_session()
    if not s:
        s = api.start_session()
    sid = s["id"]
    for _ in range(120):
        st = api.req("GET", f"/api/sessions/{sid}")["state"]
        if st == "active":
            return sid
        if st == "ready":
            api.req("POST", f"/api/sessions/{sid}/activate")
        elif st in ("failed", "aborted"):
            raise RuntimeError(f"session {sid} -> {st}")
        time.sleep(0.4)
    raise RuntimeError(f"session {sid} never became active")


GIFS = {
    "quest-start": gif_quest_start,
    "coach-chat": gif_coach_chat,
    "flag-solve": gif_flag_solve,
    "workspace-panels": gif_panels,
    "internet-toggle": gif_internet,
}


def cmd_seed(args, api: Api) -> None:
    s = api.start_session()
    sid = api.wait_state(s["id"], "ready")["id"]
    api.req("POST", f"/api/sessions/{sid}/activate")
    seed_chat(api, sid)
    print(f"session {sid} seeded ({QUEST})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["shots", "gif", "seed", "all"])
    ap.add_argument("which", nargs="?", default="all")
    ap.add_argument("--app", default="http://localhost:5173")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--password", default="pentrain-docs")
    ap.add_argument("--coach-token", default="docs-coach-token")
    ap.add_argument("--db", default="/tmp/pentrain-docs.db")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    args = ap.parse_args()

    api = Api(args.api, args.password, args.coach_token)
    api.req("GET", "/api/health")
    api.login()
    api.setup_complete()

    if args.cmd in ("seed", "all"):
        cmd_seed(args, api)
    if args.cmd in ("shots", "all"):
        cmd_shots(args, api)
    if args.cmd in ("gif", "all"):
        names = list(GIFS) if args.which == "all" else [args.which]
        for n in names:
            if n not in GIFS:
                sys.exit(f"unknown gif {n!r} — choose from {', '.join(GIFS)}")
            print(f"[gif] {n}")
            GIFS[n](args, api)


if __name__ == "__main__":
    main()
