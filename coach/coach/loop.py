"""SessionCoach: one coaching agent instance per active session.

Event model — three distinct paths:
  1. TELEMETRY (commands, exit codes, heartbeats): updates local state +
     checkpoint matching only. NEVER triggers an LLM turn by itself.
  2. USER SIGNALS (chat, flag submits): explicit chat → debounced answer;
     progress events → cheap template ack (no LLM).
  3. REFLECTION (wall-clock every reflect_interval_s, independent of event
     volume): policy decides IF the coach may speak — silence is default,
     backoff applies when proactive messages don't produce progress.
"""
from __future__ import annotations

import asyncio
import time

import structlog

from .client import BackendClient
from .config import get_config
from .llm import LlmClient, LlmError
from .policy import Policy
from .prompts import SYSTEM, build_context_msg, chat_prompt
from .state import CheckpointMatcher, SessionState

log = structlog.get_logger(__name__)

HISTORY_CAP = 14           # user/assistant messages kept in-context
CHAT_DEBOUNCE_S = 1.5      # coalesce rapid trainee messages into one turn


def _iso_to_epoch(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        import datetime as dt
        return dt.datetime.fromisoformat(iso).timestamp()
    except (ValueError, AttributeError):
        return 0.0


class SessionCoach:
    def __init__(self, session_id: int, client: BackendClient, cfg: dict,
                 *, usage: dict | None = None):
        self.sid = session_id
        self.client = client
        self.cfg = cfg
        # shared service-wide daily token counter {"day": "YYYY-MM-DD", "tokens": n}
        self.usage = usage if usage is not None else {"day": "", "tokens": 0}
        self._budget_warned = False
        self.state = SessionState(session_id=session_id)
        self.ctx: dict = {}
        self.matcher = CheckpointMatcher([])
        self.llm: LlmClient | None = None
        self.policy = Policy({}, nudge_s=480, hint_s=900)
        self._vision_model = ""
        self._history: list[dict] = []       # rolling conversation for LLM context
        self._task: asyncio.Task | None = None
        self._chat_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=2000)
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._next_reflect = time.monotonic() + 60
        self._llm_lock = asyncio.Lock()      # serialize LLM turns (chat vs reflect)
        self._coach_cmds: list[tuple[str, float]] = []   # commands we issued via exec
        self._last_capture_ts = 0.0
        self._last_badflag_ack = 0.0
        self._disabled_notice_sent = False
        self._draft_seq = 0
        self._active_draft: str | None = None   # draft_id for send_chat meta
        self._draft_used = False                 # meta attaches only once

    # ---------- lifecycle ----------

    async def start(self) -> bool:
        """Attach to the session. Returns False when there's nothing to coach
        (terminal state) — the service must not register a zombie."""
        self.ctx = await self.client.session_context(self.sid)
        s = self.ctx.get("session", {})
        # ghost guard: backend 404/error yields {} — never coach a phantom
        if not s.get("id") or not self.ctx.get("quest"):
            await log.awarning("coach attach aborted — no session context", session=self.sid)
            return False
        if s.get("state") in ("solved", "aborted", "failed"):
            return False
        self.state.autonomy_level = int(s.get("autonomy_level", 2))
        # session toggle AND global coach.enabled gate (settings screen killswitch)
        global_on = bool(self.cfg.get("coach", {}).get("enabled", True))
        self.state.coach_enabled = bool(s.get("coach_enabled", True)) and global_on
        self.state.state = s.get("state", "ready")
        self.state.checkpoints_hit = set(self.ctx.get("checkpoints_hit", []))
        self.state.flags_solved = {f["key"] for f in self.ctx.get("flags", []) if f.get("solved")}
        self.state.exec_count = int(self.ctx.get("exec_count", 0))
        self.matcher = CheckpointMatcher(self.ctx.get("quest", {}).get("checkpoints", []))
        esc = self.ctx.get("quest", {}).get("escalation", {})
        coach_cfg = self.cfg.get("coach", {})
        self.policy = Policy(
            esc,
            nudge_s=int(coach_cfg.get("nudge_after_s", 480)),
            hint_s=int(coach_cfg.get("hint_after_s", 900)),
            verbosity=coach_cfg.get("verbosity", "normal"),
        )
        llm = self.cfg.get("llm", {})
        self.llm = LlmClient(
            llm.get("base_url", ""), llm.get("api_key", ""), llm.get("model", ""),
            temperature=float(llm.get("temperature", 0.4)),
            timeout_s=get_config().llm_timeout_s,
        )
        self._vision_model = llm.get("vision_model", "")
        # seed history from the NEWEST messages (ctx messages are newest-first)
        recent = list(self.ctx.get("messages", []))[:HISTORY_CAP]
        for m in reversed(recent):
            if m.get("role") == "user":
                self._history.append({"role": "user", "content": m.get("content", "")[:900]})
            elif m.get("role") == "coach":
                self._history.append({"role": "assistant", "content": m.get("content", "")[:900]})
        # replay telemetry tail with real timestamps (chronological order);
        # command_result pairs attach directly — the 60s freshness guard in
        # mark_exit would drop them for old commands
        expect_result = False
        for ev in reversed(self.ctx.get("telemetry_tail", [])):
            payload = ev.get("payload") or {}
            if ev.get("kind") == "command":
                cmd = payload.get("command", "")
                if cmd:
                    self.state.add_command(payload.get("ts", time.time()), cmd,
                                           payload.get("cwd", ""))
                    expect_result = True
            elif ev.get("kind") == "command_result" and expect_result:
                if self.state.commands:
                    self.state.commands[-1].exit_code = int(
                        payload.get("exit_code", 0))
                expect_result = False
        # stuck/idle clocks seed from the most RECENT liveness signal —
        # not blindly from started_at (a session parked in 'ready' for hours
        # then activated must not look stuck-since-forever)
        seeds = [_iso_to_epoch(s.get("started_at")),
                 _iso_to_epoch(s.get("ready_at")),
                 self.state.last_activity_ts]
        self.state.last_progress_ts = max((x for x in seeds if x), default=time.time())
        if self.state.last_activity_ts <= 0:
            self.state.last_activity_ts = self.state.last_progress_ts
        self._ready.set()
        self._task = asyncio.create_task(self._run())
        await log.ainfo("coach attached", session=self.sid,
                        autonomy=self.state.autonomy_level)
        await self._maybe_welcome()
        return True

    async def stop(self) -> None:
        self._stop.set()
        for t in (self._task, self._chat_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        if self.llm:
            close = getattr(self.llm, "close", None)
            if close:
                await close()

    async def apply_cfg(self, cfg: dict) -> None:
        """Live config refresh — settings changed in the UI must reach running
        coaches, not just newly attached ones."""
        old_llm = self.cfg.get("llm", {})
        self.cfg = cfg
        cc = cfg.get("coach", {})
        esc = self.ctx.get("quest", {}).get("escalation", {})
        self.policy = Policy(
            esc,
            nudge_s=int(cc.get("nudge_after_s", 480)),
            hint_s=int(cc.get("hint_after_s", 900)),
            verbosity=cc.get("verbosity", "normal"),
        )
        global_on = bool(cc.get("enabled", True))
        s = self.ctx.get("session", {})
        self.state.coach_enabled = bool(s.get("coach_enabled", True)) and global_on
        llm = cfg.get("llm", {})
        if (llm.get("base_url"), llm.get("api_key"), llm.get("model"),
                llm.get("temperature")) != (
                old_llm.get("base_url"), old_llm.get("api_key"),
                old_llm.get("model"), old_llm.get("temperature")):
            new = LlmClient(
                llm.get("base_url", ""), llm.get("api_key", ""),
                llm.get("model", ""),
                temperature=float(llm.get("temperature", 0.4)),
                timeout_s=get_config().llm_timeout_s)
            old, self.llm = self.llm, new
            if old:
                await old.close()
        self._vision_model = llm.get("vision_model", "")

    async def resync(self) -> None:
        """Re-fetch session context and merge — repairs drift after the event
        stream dropped (missed flags/checkpoints/state transitions)."""
        try:
            ctx = await self.client.session_context(self.sid)
        except Exception as e:
            await log.awarning("coach resync failed", session=self.sid, error=str(e))
            return
        s = ctx.get("session") or {}
        if not s.get("id"):
            return
        self.ctx = ctx
        self.state.state = s.get("state", self.state.state)
        self.state.autonomy_level = int(s.get("autonomy_level", self.state.autonomy_level))
        global_on = bool(self.cfg.get("coach", {}).get("enabled", True))
        self.state.coach_enabled = bool(s.get("coach_enabled", True)) and global_on
        self.state.checkpoints_hit = set(ctx.get("checkpoints_hit", []))
        self.state.flags_solved = {f["key"] for f in ctx.get("flags", []) if f.get("solved")}
        self.state.exec_count = int(ctx.get("exec_count", 0))
        await log.ainfo("coach resynced", session=self.sid, state=self.state.state)

    async def feed(self, event: dict) -> None:
        if self._stop.is_set():
            return  # dead coach — don't fill a queue nobody drains
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            await log.awarning("coach event queue full — dropping event",
                               session=self.sid, type=event.get("type"))

    async def _maybe_welcome(self) -> None:
        """Greet once per session — not on every coach restart."""
        if any(m.get("role") == "assistant" for m in self._history):
            return  # already spoke — this is a restart/re-attach
        if not self.state.coach_enabled:
            return
        title = self.ctx.get("quest", {}).get("title", "your quest")
        if self.state.state in ("queued", "deploying"):
            text = (f"Welcome — **{title}** is deploying. This can take a few "
                    "minutes; meanwhile, skim the briefing on the left.")
        elif self.state.state in ("ready", "active"):
            text = (f"Welcome to **{title}** — your range is ready. Start in the "
                    "Kali desktop; I'm watching and will only chime in if you "
                    "get stuck.")
        else:
            return
        await self.client.send_chat(self.sid, text, kind="nudge",
                                    meta={"auto": True})
        self._record_reply(text)  # model must see what the trainee already saw

    # ---------- event handling ----------

    async def _run(self) -> None:
        reflect = float(self.cfg.get("coach", {}).get("reflect_interval_s", 60))
        while not self._stop.is_set():
            try:
                timeout = max(2.0, self._next_reflect - time.monotonic())
                ev = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                await self._handle_event(ev)
                # drain burst — but never starve the reflection timer
                drained = 0
                while True:
                    try:
                        await self._handle_event(self._queue.get_nowait())
                        drained += 1
                        if drained % 64 == 0 and time.monotonic() >= self._next_reflect:
                            await self._reflect_tick(reflect)
                    except asyncio.QueueEmpty:
                        break
                if time.monotonic() >= self._next_reflect:
                    await self._reflect_tick(reflect)
            except TimeoutError:
                await self._reflect_tick(reflect)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await log.aexception("coach event error", error=str(e))

    async def _handle_event(self, ev: dict) -> None:
        etype = ev.get("type")
        topic = ev.get("topic", "")
        data = ev.get("data", {}) or {}
        try:
            sid = int(data.get("session_id") or (ev.get("session_id") or 0))
        except (TypeError, ValueError):
            return
        if sid != self.sid:
            return

        # path 1: telemetry — silent state update, never an LLM turn
        if topic.startswith("telemetry."):
            kind = data.get("kind")
            payload = data.get("payload", {}) or {}
            if kind == "command":
                cmd = payload.get("command", "")
                self.state.add_command(
                    payload.get("ts", time.time()), cmd,
                    payload.get("cwd", ""), payload.get("exit_code"),
                    from_coach=self._is_coach_command(cmd))
                for cid in self.matcher.check(cmd):
                    if cid not in self.state.checkpoints_hit:
                        self.state.checkpoints_hit.add(cid)
                        self.state.progress()
                        await self.client.mark_checkpoint(self.sid, cid)
                        await self._quick_ack(
                            f"Checkpoint: **{self.matcher.name_for(cid)}** — logged.")
            elif kind == "command_result":
                self.state.mark_exit(int(payload.get("exit_code", 0)))
            # heartbeats & other kinds → ignored entirely

        # path 2: session/user signals
        elif topic.startswith("session."):
            if etype == "state":
                self.state.state = data.get("state", self.state.state)
                if data.get("state") == "solved":
                    await self._on_solved()
                elif data.get("state") == "ready":
                    await self._maybe_welcome()
            elif etype == "flag":
                if data.get("correct"):
                    self.state.progress()
                    fk = data.get("flag_key") or "?"
                    self.state.flags_solved.add(fk)
                    if data.get("all_solved"):
                        await self._quick_ack("All flags captured — quest complete.")
                    else:
                        await self._quick_ack(f"Flag `{fk}` accepted.")
                else:
                    # spam-guard: a frustrated trainee may hammer wrong flags
                    if time.time() - self._last_badflag_ack > 15:
                        self._last_badflag_ack = time.time()
                        await self._quick_ack("That flag value isn't right. Keep going.")
            elif etype == "checkpoint":
                self.state.progress()
            # suggest_command_confirm broadcasts on the session.* topic
            elif etype == "coach_action" and data.get("status") in ("confirmed", "rejected"):
                self.state.progress()  # trainee engaged with a suggestion
        elif topic.startswith("coach."):
            if etype == "coach_message" and data.get("role") == "user":
                if self.state.coach_enabled:
                    self._buffer_chat(data.get("content", ""))
                elif not self._disabled_notice_sent:
                    # one-time notice instead of a silent void
                    self._disabled_notice_sent = True
                    await self._quick_ack(
                        "Coach is disabled for this session — you're on your own.")
            elif etype == "coach_action" and data.get("status") in ("confirmed", "rejected"):
                self.state.progress()

    def _is_coach_command(self, cmd: str) -> bool:
        """Did WE just type this via exec_in_kali? The tmux path appends a
        ` ; echo PTNxxx:$?` marker suffix — match on prefix, short window."""
        now = time.time()
        self._coach_cmds = [(c, t) for c, t in self._coach_cmds if now - t < 20]
        logged = cmd.strip()
        for i, (c, _t) in enumerate(self._coach_cmds):
            if logged == c.strip() or logged.startswith(c.strip()):
                self._coach_cmds.pop(i)
                return True
        return False

    def _buffer_chat(self, content: str) -> None:
        """Coalesce rapid trainee messages into one debounced LLM turn."""
        if len(self.state.pending_chat) >= 10:
            return  # bound the buffer — spam can't grow it
        self.state.pending_chat.append(content[:1500])
        if not self._chat_task or self._chat_task.done():
            self._chat_task = asyncio.create_task(self._chat_debounced())

    async def _chat_debounced(self) -> None:
        try:
            await asyncio.sleep(CHAT_DEBOUNCE_S)
            if not self.state.pending_chat:
                return
            text = "\n".join(self.state.pending_chat)
            self.state.pending_chat.clear()
            await self._answer_chat(text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # never leave the trainee hanging without a trace
            await log.aexception("chat answer failed", session=self.sid, error=str(e))

    # ---------- LLM turns ----------

    async def _quick_ack(self, text: str) -> None:
        """Cheap template ack — no LLM call, keeps progress noise minimal."""
        await self.client.send_chat(self.sid, text, kind="nudge",
                                    meta={"auto": True})
        # model must see what the trainee already saw — avoids repeats
        self._record_reply(text)

    async def _reflect_tick(self, reflect_s: float) -> None:
        self._next_reflect = time.monotonic() + reflect_s
        if not self.llm or not self.state.coach_enabled:
            return
        decision = self.policy.evaluate(self.state)
        if not decision.may_proactive:
            return
        budget = int(self.cfg.get("coach", {}).get("action_budget", 50))
        spoke = await self._llm_turn(
            build_context_msg(self.ctx, self.state, decision.reason,
                              decision.urgency, stage=decision.stage,
                              action_budget=budget),
            proactive=True)
        if spoke:
            self.state.proactive_streak += 1

    async def _answer_chat(self, user_msg: str) -> None:
        if not self.llm or not self.state.coach_enabled:
            return
        await self._llm_turn(chat_prompt(user_msg), force_reply=True,
                             record_user=user_msg)

    async def _on_solved(self) -> None:
        await self._quick_ack("Quest solved. Nice work — check the Defense tab for the fix.")
        # write back skill progression for future sessions
        try:
            track = self.ctx.get("quest", {}).get("track", "")
            levels = dict(self.ctx.get("profile", {}).get("track_levels") or {})
            cur = int(levels.get(track, 0) or 0)
            await self.client.update_profile(track_levels={track: min(5, cur + 1)})
        except Exception as e:
            await log.awarning("profile writeback failed", error=str(e))

    def _budget_exceeded(self) -> bool:
        """Roll the shared daily counter at day change, then compare vs config."""
        import datetime as _dt
        today = _dt.date.today().isoformat()
        if self.usage.get("day") != today:
            self.usage["day"] = today
            self.usage["tokens"] = 0
            self._budget_warned = False
        budget = int(self.cfg.get("llm", {}).get("daily_token_budget") or 0)
        return budget > 0 and self.usage["tokens"] >= budget

    async def _llm_turn(self, user_msg: str, *, force_reply: bool = False,
                        proactive: bool = False, record_user: str | None = None
                        ) -> bool:
        """One LLM turn, serialized via lock (chat + reflect must not interleave).
        `record_user` = the raw text remembered as the trainee's message (the
        wrapped prompt itself is scaffolding, not conversation).
        Returns True if it produced any visible output."""
        assert self.llm is not None
        if self._budget_exceeded():
            if not self._budget_warned:
                self._budget_warned = True
                await self.client.send_chat(
                    self.sid,
                    "Daily LLM token budget reached — coach pauses until tomorrow. "
                    "Raise llm.daily_token_budget in Settings to continue.",
                    kind="nudge")
            return False
        if record_user:
            self._history.append({"role": "user", "content": record_user[:900]})
            self._history = self._history[-HISTORY_CAP:]
        async with self._llm_lock:
            messages = [{"role": "system", "content": SYSTEM}]
            messages += self._history
            messages.append({"role": "user", "content": user_msg})
            # streaming draft: deltas flow to the UI while the model writes;
            # the first real message this turn posts carries meta.draft_id so
            # the draft bubble is replaced atomically
            self._draft_seq += 1
            draft_id = f"{self.sid}d{self._draft_seq}"
            self._active_draft = draft_id
            self._draft_used = False
            pushed = False
            last_push = 0.0
            kind = "nudge" if proactive else "message"

            async def on_delta(cum: str) -> None:
                nonlocal pushed, last_push
                if not get_config().llm_stream:
                    return
                now = time.monotonic()
                if pushed and now - last_push < 0.12:
                    return  # throttle — LAN relay, ~8 msgs/s is plenty
                pushed = True
                last_push = now
                await self.client.stream_draft(self.sid, draft_id, cum, kind=kind)

            try:
                resp = await self.llm.chat(messages, on_delta=on_delta)
            except LlmError as e:
                await log.awarning("llm call failed", error=str(e))
                if pushed:
                    await self.client.stream_draft(self.sid, draft_id, "", done=True)
                self._active_draft = None
                return False
            usage = (resp.get("raw") or {}).get("usage") or {}
            self.usage["tokens"] += int(usage.get("total_tokens", 0))
            spoke = False
            for a in resp["actions"]:
                # model "reasoning notes" become working memory for later turns
                if a.get("type") == "none" and a.get("reason"):
                    self.state.notes.append(str(a["reason"])[:300])
                    self.state.notes = self.state.notes[-8:]
                spoke |= await self._dispatch(a, proactive=proactive)
            if not spoke and force_reply:
                text = resp["content"][:1500]
                await self.client.send_chat(self.sid, text, meta=self._draft_meta())
                self._record_reply(text)
                spoke = True
            if pushed:
                # draft's job is done — the real message (with draft_id meta)
                # replaces it; done is the failsafe for turns with no chat
                await self.client.stream_draft(self.sid, draft_id, "", done=True)
            self._active_draft = None
            return spoke

    def _record_reply(self, text: str) -> None:
        self._history.append({"role": "assistant", "content": text[:900]})
        self._history = self._history[-HISTORY_CAP:]

    def _draft_meta(self) -> dict:
        """Attach the active draft_id to the FIRST message this turn posts —
        the UI swaps the streaming bubble for the real message by this key."""
        if self._active_draft and not self._draft_used:
            self._draft_used = True
            return {"draft_id": self._active_draft}
        return {}

    # ---------- action dispatch ----------

    async def _dispatch(self, a: dict, *, proactive: bool = False) -> bool:
        """Execute one LLM action under autonomy/budget gates. Returns True if visible."""
        t = a.get("type")
        level = self.state.autonomy_level
        spoke = False

        if t == "send_chat":
            content = (a.get("content") or "").strip()[:2000]
            if not content:
                return spoke
            kind = "nudge" if proactive else "message"
            await self.client.send_chat(self.sid, content, kind=kind,
                                        meta=self._draft_meta())
            self._record_reply(content)
            spoke = True
        elif t == "offer_hint":
            content = (a.get("content") or "").strip()[:2000]
            if not content:
                return spoke
            level = min(3, max(1, int(a.get("level") or 1)))
            await self.client.send_chat(self.sid, content, kind="hint",
                                        meta={"level": level, **self._draft_meta()})
            self._record_reply(content)
            self.state.last_hint_ts = time.time()
            spoke = True
        elif t == "suggest_command":
            cmd = (a.get("command") or a.get("content") or "").strip()
            if level >= 3 and cmd:
                await self.client.suggest_command(
                    self.sid, cmd, a.get("why", ""))
                # remember we asked — the trainee may confirm or reject
                self._record_reply(f"[suggested command] `{cmd}` — {a.get('why', '')}")
                spoke = True
        elif t == "exec_in_kali":
            if level >= 4:
                budget = int(self.cfg.get("coach", {}).get("action_budget", 50))
                if self.state.exec_count >= budget:
                    await self.client.send_chat(
                        self.sid, "Coach action budget reached — manual takeover disabled this session.",
                        kind="nudge")
                else:
                    cmd = (a.get("command") or a.get("content", "")).strip()
                    if not cmd:
                        return spoke
                    # mark BEFORE the call so telemetry echo is recognized as ours
                    self._coach_cmds.append((cmd, time.time()))
                    res = await self.client.exec_in_kali(self.sid, cmd)
                    if res.get("status") == "denied" or res.get("error"):
                        # never actually typed → a stale entry could mislabel a
                        # user-typed identical command
                        self._coach_cmds.pop()
                    else:
                        self.state.exec_count += 1
                    out = (res.get("out") or res.get("error") or "")[:500]
                    note = ("\n\n*(typed live in the `pentrain-coach` tmux)*"
                            if res.get("visible") else "")
                    text = f"Executed: `{cmd}`\n```\n{out}\n```{note}"
                    await self.client.send_chat(self.sid, text, kind="action_report")
                    self._record_reply(text)
                    spoke = True
        elif t == "mark_checkpoint":
            cid = a.get("checkpoint_id")
            # only accept checkpoints the quest actually defines
            known = {c for c, _n, _p in self.matcher._rules}
            if cid and cid in known and cid not in self.state.checkpoints_hit:
                self.state.checkpoints_hit.add(cid)
                await self.client.mark_checkpoint(self.sid, cid)
        elif t == "capture_screen":
            # rate-limit: one capture per 30s regardless of model enthusiasm
            if time.time() - self._last_capture_ts > 30:
                self._last_capture_ts = time.time()
                res = await self.client.capture_screen(self.sid)
                if res.get("png_b64"):
                    self.state.screen_desc = await self._describe_screen(res["png_b64"])
        # "none" or unknown → silence (reason captured above as working memory)
        if spoke:
            self.state.last_nudge_ts = time.time()
            self.state.nudges_sent += 1
        return spoke

    async def _describe_screen(self, png_b64: str) -> str:
        """Send the screenshot to a vision-capable model for a text description."""
        if not self._vision_model or not self.llm:
            return "screenshot captured but no vision_model configured"
        if self._budget_exceeded():
            return "screenshot captured but token budget exhausted"
        try:
            resp = await self.llm.chat([{
                "role": "user",
                "content": [
                    {"type": "text", "text": "You are coaching a pentest trainee. "
                                             "Describe what is on this Kali desktop in 2-3 "
                                             "sentences — tools open, terminals, errors visible."},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                ],
            }], json_mode=False, model=self._vision_model)
            usage = (resp.get("raw") or {}).get("usage") or {}
            self.usage["tokens"] += int(usage.get("total_tokens", 0))
            return (resp.get("content") or "")[:600]
        except LlmError as e:
            return f"vision capture failed: {e}"
