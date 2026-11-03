"""Session observer — the knowledge system's write side.

The coach only READS knowledge (modules via lookup_guide, field notes via
push-hints); this service is the only writer. It tails each session's
trajectory file and produces three kinds of output:

1. LIVE TIPS — when the coach is stuck (no progress + denial/loop
   signals), one concrete technique-level unblock suggestion lands on the
   next tool result via `observer_hint` (guaranteed-read channel).
2. FIELD NOTES — when a stuck phase resolves (recovery) and at session
   end (postmortem), the window is distilled into reusable lessons stored
   in `coach_lessons` (status=active, always rendered '[unverified]').
3. LIVE DELIVERY — a fresh note whose scope matches a running session is
   pushed straight in, so new knowledge reaches a live coach without
   waiting for a re-attach.

Triggers are deterministic (traj facts counters, denial counts, command
repeats); only the distillation uses the LLM. Everything is bounded:
≤2 proposals per analysis, ≤4 lessons per session, 15 min cooldowns,
one advisory per stuck episode.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from collections import Counter, deque
from pathlib import Path

import structlog

from .llm import LlmClient

log = structlog.get_logger(__name__)

_ANALYSIS_BUDGET = 8000       # chars of traj window sent to the LLM
_NOTE_PREVIEW = 200           # hint text cap for pushed notes
_PROGRESS_KEYS = ("hosts", "creds", "files", "flags")
_POSITIVE_RES = re.compile(r"correct|solved|accepted|\bhit\b", re.IGNORECASE)


class _Watch:
    """Per-session detector state — rebuilt from the traj file each tick."""

    __slots__ = (
        "advisory_sent",
        "analyses",
        "ctx",
        "ctx_ts",
        "denials",
        "facts_seen",
        "last_analysis_ts",
        "last_progress_ts",
        "lessons",
        "offset",
        "postmortem_done",
        "repeats",
        "sid",
        "stuck_since",
        "window",
    )

    def __init__(self, sid: int) -> None:
        self.sid = sid
        self.offset = 0
        self.last_progress_ts = time.time()   # grace period on first sight
        self.denials: deque[float] = deque(maxlen=64)
        self.repeats: deque[tuple[str, float]] = deque(maxlen=64)
        self.stuck_since = 0.0
        self.advisory_sent = False
        self.analyses = 0                      # LLM calls made
        self.lessons = 0                       # proposals accepted by backend
        self.last_analysis_ts = 0.0
        self.postmortem_done = False
        self.ctx: dict = {}
        self.ctx_ts = 0.0
        self.facts_seen: dict = {}
        self.window: deque[dict] = deque(maxlen=240)


class ObserverService:
    """Async sibling of CoachService — polls active sessions, tails their
    traj files, runs the detectors, and writes back via the backend."""

    def __init__(self, client, cfg_getter) -> None:
        self.client = client
        self._cfg_getter = cfg_getter       # async callable → cfg dict
        self._watch: dict[int, _Watch] = {}
        self._llm: LlmClient | None = None
        self._llm_sig: tuple = ()
        self._lesson_texts: list[str] = []  # dedupe base (cached 5 min)
        self._lessons_ts = 0.0

    # ---------- main loop ----------

    async def run(self) -> None:
        log.info("observer started")
        while True:
            try:
                cfg = await self._cfg_getter()
                obs = (cfg or {}).get("coach", {})
                if obs.get("observer_enabled", True):
                    await self._tick(obs)
            except Exception as e:
                # the observer must never take the coach down with it
                await log.aexception("observer tick failed", error=repr(e))
            await asyncio.sleep(float(obs.get("observer_tick_s", 60)))

    async def _tick(self, obs: dict) -> None:
        try:
            active = {int(s["id"]) for s in await self.client.active_sessions()
                      if s.get("state") == "active"}
        except Exception:
            return
        # sessions that left the active set → one postmortem each
        for sid in list(self._watch):
            w = self._watch[sid]
            if sid not in active and not w.postmortem_done:
                w.postmortem_done = True
                await self._postmortem(w, obs)
            if sid not in active:
                del self._watch[sid]
        for sid in active:
            w = self._watch.setdefault(sid, _Watch(sid))
            await self._scan(w, obs)

    # ---------- trajectory tail + detectors ----------

    async def _scan(self, w: _Watch, obs: dict) -> None:
        new = self._tail(w.sid, w.offset)
        if new is None:
            return
        lines, consumed = new
        w.offset += consumed
        recovery = False
        for raw in lines:
            ev = None
            with contextlib.suppress(Exception):
                ev = json.loads(raw)
            if not isinstance(ev, dict):
                continue
            w.window.append(ev)
            if self._consume(w, ev):
                recovery = True
        now = time.time()
        if recovery and w.stuck_since:
            # stuck→recovery — the payoff trigger
            await self._analyze_lessons(w, obs, trigger="recovery",
                                        since=w.stuck_since)
            w.stuck_since = 0.0
            w.advisory_sent = False
        if self._is_stuck(w, obs, now):
            if not w.stuck_since:
                w.stuck_since = w.last_progress_ts
            # mid-stuck advisory — the tip that replaces manual nudges
            if (not w.advisory_sent
                    and await self._autonomy_ok(w, obs)):
                await self._analyze_advisory(w, obs)

    @staticmethod
    def _traj_path(sid: int) -> Path:
        d = os.environ.get("PENTRAIN_TRAJ_DIR", "./traj")
        return Path(d) / f"session-{sid}.jsonl"

    def _tail(self, sid: int, offset: int) -> tuple[list[str], int] | None:
        """New complete traj lines since the last tick + bytes consumed.
        The tail may catch a line mid-write — only consume up to the last
        newline so a partial record is retried on the next tick."""
        try:
            p = self._traj_path(sid)
            if not p.exists() or p.stat().st_size <= offset:
                return [], 0
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(offset)
                data = fh.read()
            nl = data.rfind("\n")
            if nl < 0:
                return [], 0
            return data[:nl].splitlines(), nl + 1
        except OSError:
            return None

    def _consume(self, w: _Watch, ev: dict) -> bool:
        """Update detector counters from one traj line; True on progress."""
        ts = float(ev.get("ts") or 0)
        progress = False
        if ev.get("kind") == "denial":
            w.denials.append(ts)
        if ev.get("kind") == "turn":
            for a in ev.get("actions") or []:
                if a.get("denied"):
                    w.denials.append(ts)
                    continue
                # repeated identical tool+first-arg = a loop, not progress
                first = str(a.get("arg") or "").strip().split(" ", 1)[0]
                w.repeats.append((f"{a.get('t')}:{first}", ts))
                if (a.get("t") in ("submit_flag", "check_flag")
                        and _POSITIVE_RES.search(str(a.get("res") or ""))):
                    progress = True
            facts = ev.get("facts") or {}
            if any(int(facts.get(k) or 0) > int(w.facts_seen.get(k) or 0)
                   for k in _PROGRESS_KEYS):
                progress = True
            w.facts_seen = {k: facts.get(k) for k in facts} or w.facts_seen
        if progress:
            w.last_progress_ts = ts or time.time()
        return progress

    def _is_stuck(self, w: _Watch, obs: dict, now: float) -> bool:
        """Stuck = a progress drought plus failure evidence — mirrors the
        coach's own reflect logic but measured on the persisted record."""
        if now - w.last_progress_ts < float(obs.get("observer_stuck_s", 600)):
            return False
        win_denials = [t for t in w.denials if t > w.last_progress_ts]
        if len(win_denials) >= int(obs.get("observer_min_denials", 2)):
            return True
        rep = Counter(tok for tok, t in w.repeats
                      if t > w.last_progress_ts)
        return bool(rep) and rep.most_common(1)[0][1] >= 3

    # ---------- analysis ----------

    async def _ctx(self, w: _Watch) -> dict:
        """Session metadata for prompts (quest/track/autonomy), cached 5min."""
        if time.time() - w.ctx_ts > 300 or not w.ctx:
            with contextlib.suppress(Exception):
                w.ctx = await self.client.session_context(w.sid)
            w.ctx_ts = time.time()
        return w.ctx or {}

    async def _autonomy_ok(self, w: _Watch, obs: dict) -> bool:
        ctx = await self._ctx(w)
        level = int((ctx.get("session") or {}).get("autonomy_level") or 0)
        return level >= int(obs.get("observer_hint_min_level", 3))

    async def _get_llm(self, obs: dict) -> LlmClient | None:
        llmc = (await self._cfg_getter() or {}).get("llm") or {}
        sig = (llmc.get("base_url"), llmc.get("model"))
        if not sig[0]:
            return None
        if not self._llm or self._llm_sig != sig:
            with contextlib.suppress(Exception):
                if self._llm:
                    await self._llm.close()
            self._llm = LlmClient(
                base_url=sig[0], api_key=str(llmc.get("api_key") or ""),
                model=str(sig[1] or ""), timeout_s=240,
                reasoning=bool(llmc.get("reasoning", True)),
                # advisory/lesson distillation is lightweight analysis —
                # "high" effort on a local 27B blows past the 240s cap
                # (observed: observer lesson llm timed out mid-session)
                reasoning_effort="low")
            self._llm_sig = sig
        return self._llm

    @staticmethod
    def _window_text(window: list[dict], budget: int = _ANALYSIS_BUDGET) -> str:
        """Compact action dump: tool, arg head, result head, denied flag."""
        lines = []
        for ev in window:
            for a in ev.get("actions") or []:
                tag = " DENIED" if a.get("denied") else ""
                lines.append(
                    f"{a.get('t')}{tag}: {str(a.get('arg'))[:140]} => "
                    f"{str(a.get('res'))[:200]}")
        text = "\n".join(lines)
        return text[-budget:]

    async def _dedupe_base(self) -> list[str]:
        if time.time() - self._lessons_ts > 300 or not self._lesson_texts:
            with contextlib.suppress(Exception):
                rows = await self.client.list_lessons()
                self._lesson_texts = [
                    str(r.get("text") or "") for r in (rows or [])
                    if r.get("status") == "active"]
            self._lessons_ts = time.time()
        return self._lesson_texts

    async def _analyze_advisory(self, w: _Watch, obs: dict) -> None:
        """One concrete unblock tip mid-stuck — the live equivalent of the
        manual nudges the capstone runs kept needing."""
        w.advisory_sent = True
        if w.analyses >= 8:
            return
        llm = await self._get_llm(obs)
        if not llm:
            return
        ctx = await self._ctx(w)
        quest = ctx.get("quest") or {}
        msgs = [{"role": "system", "content": (
            "You observe an autonomous pentest coach that is STUCK — repeated "
            "denials or tool loops with no progress. Propose ONE concrete "
            "next step it has not tried: a technique, an alternate tool, or "
            "a different vantage. Rules: ≤2 sentences, technique-level "
            "(never the flag answer), no invented paths or creds, plain "
            "text only (no markdown).")}, {"role": "user", "content": (
            f"quest: {quest.get('title','?')} track={quest.get('track','?')} "
            f"tier={quest.get('tier','?')}\n\n"
            f"recent actions (newest last):\n{self._window_text(list(w.window))}")}]
        w.analyses += 1
        try:
            resp = await llm.chat(msgs, json_mode=False)
            text = str(resp.get("content") or "").strip()
        except Exception as e:
            await log.awarning("observer advisory llm failed",
                               session=w.sid, error=repr(e))
            return
        text = self._sanitize(text, advisory=True)
        if len(text) < 20:
            return
        await self.client.observer_hint(w.sid, text)
        await self.client.log_action(w.sid, "observe_hint", {"text": text[:300]},
                                     {"delivered": True})
        await log.ainfo("observer advisory sent", session=w.sid, hint=text[:120])

    async def _analyze_lessons(self, w: _Watch, obs: dict, *, trigger: str,
                               since: float) -> None:
        """Distill a stuck→recovery (or postmortem) window into ≤2 reusable
        field notes — the knowledge write path."""
        now = time.time()
        if (w.lessons >= int(obs.get("observer_max_lessons_session", 4))
                or now - w.last_analysis_ts <
                float(obs.get("observer_cooldown_s", 900))):
            return
        llm = await self._get_llm(obs)
        if not llm:
            return
        ctx = await self._ctx(w)
        quest = ctx.get("quest") or {}
        known = await self._dedupe_base()
        window = [ev for ev in w.window
                  if float(ev.get("ts") or 0) >= since]
        msgs = [{"role": "system", "content": (
            "You distill an autonomous pentest coach's experience into "
            "reusable FIELD NOTES for future sessions. The coach was stuck, "
            "then made progress (or the session ended). Write at most "
            f"{int(obs.get('observer_max_proposals', 2))} tips that "
            "generalize beyond this quest: technique recipes, environment "
            "facts, dead ends to skip. Rules: each ≤200 chars, "
            "technique-level — NEVER a flag value, password, or quest-"
            "specific answer; 2-6 lowercase trigger tags each (terms that "
            "would appear in a relevant command/output like 'ssh', '.git', "
            "'filtered'); JSON only.")}, {"role": "user", "content": (
            f"quest: {quest.get('title','?')} track={quest.get('track','?')} "
            f"tier={quest.get('tier','?')} trigger={trigger}\n\n"
            "existing notes (do not restate):\n- "
            + "\n- ".join(known[:30])
            + f"\n\nsession window:\n{self._window_text(window)}"
            + '\n\nJSON: {"proposals":[{"text":"…","tags":["…"],'
              '"applies":"global","confidence":0.7}]} or {"proposals":[]}')}]
        w.last_analysis_ts = now
        w.analyses += 1
        try:
            resp = await llm.chat(msgs)
            proposals = self._parse_proposals(resp)
        except Exception as e:
            await log.awarning("observer lesson llm failed",
                               session=w.sid, error=repr(e))
            return
        track = str(quest.get("track") or "")
        for p in proposals[: int(obs.get("observer_max_proposals", 2))]:
            text = self._sanitize(str(p.get("text") or ""))
            if len(text) < 20 or self._is_dup(text, known):
                continue
            applies = str(p.get("applies") or "global")
            if applies == f"track:{track}" or not applies.startswith(
                    ("global", "track:", "quest:")):
                applies = "global"
            row = await self.client.create_lesson(
                w.sid, text, list(p.get("tags") or [])[:8], applies,
                float(p.get("confidence") or 0.5),
                {"session_id": w.sid, "trigger": trigger,
                 "quest": quest.get("id")})
            if isinstance(row, dict) and row.get("id"):
                w.lessons += 1
                known.append(text)
                await self.client.log_action(
                    w.sid, "observe_lesson",
                    {"text": text[:240], "trigger": trigger},
                    {"lesson_id": row["id"]})
                await log.ainfo("observer lesson stored", session=w.sid,
                                lesson_id=row["id"], text=text[:100])
                # T4: scope-matched live delivery into other watched sessions
                for other in list(self._watch.values()):
                    if other.sid != w.sid:
                        await self._deliver_note(other, applies, text,
                                                 quest_id=quest.get("id"))

    async def _postmortem(self, w: _Watch, obs: dict) -> None:
        """Session ended — one final distillation of the whole tail."""
        await self._analyze_lessons(w, obs, trigger="postmortem", since=0.0)

    async def _deliver_note(self, w: _Watch, applies: str, text: str,
                            quest_id=None) -> None:
        """Push a fresh note into another live session when its scope
        matches — new knowledge shouldn't wait for the next re-attach."""
        octx = await self._ctx(w)
        oquest = octx.get("quest") or {}
        if applies == "global" or \
                applies == f"track:{oquest.get('track')}" or \
                (quest_id is not None and applies == f"quest:{quest_id}"
                 and oquest.get("id") == quest_id):
            await self.client.observer_hint(
                w.sid, f"field note: {text[:_NOTE_PREVIEW]}")

    # ---------- validation ----------

    @staticmethod
    def _parse_proposals(resp: dict) -> list:
        """Tolerant JSON extraction — the same model emits fences/prose."""
        text = str(resp.get("content") or "")
        with contextlib.suppress(Exception):
            data = json.loads(text)
            return list(data.get("proposals") or [])
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            with contextlib.suppress(Exception):
                data = json.loads(m.group(0))
                return list(data.get("proposals") or [])
        return []

    @staticmethod
    def _sanitize(text: str, advisory: bool = False) -> str:
        """Strip anything that must never become knowledge: flag values,
        credentials, tokens. Returns '' when nothing safe remains."""
        t = str(text or "")
        t = re.sub(r"pentrAIn\{[^}]*\}", "<redacted>", t)
        t = re.sub(r"(?:-p|password|passwd|secret|token|apikey|api_key)\s*"
                   r"[=: ]\s*['\"]?\S+", "<redacted>", t,
                   flags=re.IGNORECASE)
        t = re.sub(r"Bearer\s+\S+", "<redacted>", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip().strip('"').strip()
        if t.lower() in ("<redacted>", "none", "n/a"):
            return ""
        cap = 400 if advisory else 240
        return t[:cap]

    @staticmethod
    def _is_dup(text: str, known: list[str]) -> bool:
        """Jaccard≥0.7 against active lessons — same tip, other wording."""
        def toks(s: str) -> set:
            return {w for w in re.findall(r"[a-z0-9_./-]+", s.lower())
                    if len(w) > 2}
        ta = toks(text)
        if not ta:
            return True
        for k in known:
            tb = toks(k)
            if tb and len(ta & tb) / len(ta | tb) >= 0.7:
                return True
        return False
