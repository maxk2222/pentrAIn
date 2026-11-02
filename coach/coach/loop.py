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
import contextlib
import hashlib
import ipaddress
import re
import time
from dataclasses import dataclass, field

import httpx
import structlog

from . import percept
from . import traj as _traj
from .client import BackendClient
from .config import get_config
from .facts import FLAG_RE, WRITE_RE, FactsDB, _USER_AT_HOST

# settled-denial forms rendered by percept: denied:{svc}-{user}@{host},
# denied:{svc}-auth@{host}, denied:sudo|docker@{host}, unreachable:{ip}@{v}
_DENIAL_FORM = re.compile(r"denied:(\w+)(?:-([\w.\-]+))?@(\S+)")
from . import facts as facts_mod
from .llm import LlmClient, LlmError
from .policy import Policy
from .prompts import build_context_msg, chat_prompt, plan_render, render_worker_prompt, system_prompt
from .state import CheckpointMatcher, SessionState, normalize_plan
from .tools import WORKER_TOOL_NAMES, tools_for_level, trim_history, wire_history, worker_tools

log = structlog.get_logger(__name__)

HISTORY_CAP = 14           # user/assistant messages kept in-context
CHAT_DEBOUNCE_S = 1.5      # coalesce rapid trainee messages into one turn
LLM_TURN_BUDGET_S = 300    # hard bound for one LLM turn incl. action dispatch;
                         # a wedged call gets cancelled, releasing the lock
# tool types that keep an in-turn chain alive — they have server-side effects
# whose results the model should see immediately (send_chat/offer_hint/none
# end the chain: the model only wanted to talk or pause)
_CHAIN_TOOLS = {"exec_in_kali", "type_in_pane", "submit_flag", "check_flag",
                "mark_checkpoint", "capture_screen", "suggest_command",
                "spawn_agent", "collect_agent", "agent_status", "kill_agent",
                "wait"}


@dataclass
class _Worker:
    """A spawned parallel subagent — own LLM context, own tmux window
    (pentrain-coach:wN), exec-only toolset. The parent coach collects its
    report via collect_agent."""
    id: str            # "w1".."wN"
    task: str
    status: str = "running"   # running|done|failed|killed|timeout
    report: str = ""
    actions: int = 0
    turns: int = 0
    started: float = 0.0
    merged: bool = False    # report already flowed into FactsDB
    # worker's own roadmap — update_plan under this window writes here,
    # never the parent's state.plan; audit-only persistence (workers die
    # on restart)
    plan: list[dict] = field(default_factory=list)
    task_obj: asyncio.Task | None = None


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
        self._pane_interactive = False   # pane holds a program awaiting input
        # consecutive execs that never finished — PER PANE: a worker's wedged
        # window must not escalate the parent's counter (and vice versa)
        self._busy_bounces: dict[str, int] = {}
        # consecutive wait-tool calls per pane — same per-pane rule as
        # _busy_bounces: a worker's waiting must not count against the parent
        self._wait_streak: dict[str, int] = {}
        # set by _llm_turn for the wait tool's budget guard — a sleep into a
        # dying turn would get cancelled mid-way and its result lost
        self._turn_deadline: float | None = None
        self._last_capture_ts = 0.0
        self._last_badflag_ack = 0.0
        self._disabled_notice_sent = False
        self._draft_seq = 0
        self._active_draft: str | None = None   # draft_id for send_chat meta
        self._draft_used = False                 # meta attaches only once
        self._draft_pushed = False               # any delta relayed this turn
        self._turn_reasoning = ""                # reasoning of the in-flight turn
        self.facts = FactsDB()                   # structured session memory —
        # hosts/creds/files/flags + ips_seen; feeds FACTS:, the objective
        # tracker and the anti-loop guards (rebuilt from replay on restart)
        self._out_sigs: dict[str, int] = {}      # exec output signature → count
        # file read counts live in facts.files[path].reads — persisted via
        # the coach_outputs replay so the ≥3 re-read guard survives restarts
        self._submit_challenged: dict[str, int] = {}  # unverified submits
        self._allowed_nets: list[ipaddress.IPv4Network] = []  # target /24s
        self._workers: dict[str, _Worker] = {}   # spawned subagents w1..wN
        # per-worker in-turn reasoning — attached once to that worker's next
        # posted message (pop-once), mirroring the parent's _turn_reasoning
        self._worker_reasoning: dict[str, str] = {}
        self._traj = _traj.NullTrajLog()         # JSONL turn log — real file
        # once start() binds the session (PENTRAIN_TRAJ_DIR)

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
        self.state.subagents_enabled = bool(s.get("subagents_enabled", False))
        # session toggle AND global coach.enabled gate (settings screen killswitch)
        global_on = bool(self.cfg.get("coach", {}).get("enabled", True))
        self.state.coach_enabled = bool(s.get("coach_enabled", True)) and global_on
        self.state.state = s.get("state", "ready")
        self.state.checkpoints_hit = set(self.ctx.get("checkpoints_hit", []))
        self.state.flags_solved = {f["key"] for f in self.ctx.get("flags", []) if f.get("solved")}
        self.state.exec_count = int(self.ctx.get("exec_count", 0))
        self.matcher = CheckpointMatcher(self.ctx.get("quest", {}).get("checkpoints", []))
        # known-good target space for the hallucinated-IP guard: each target's
        # /24 (or explicit CIDR — home-lab carries "lan-scope=192.168.3.131/24"),
        # plus every IP ever seen in tool output (pivot-safe — a host the model
        # discovers in output becomes reachable, one it invents does not)
        for t in (self.ctx.get("quest", {}).get("targets") or []):
            ip = (t.get("ip") or "").strip()
            if not ip:
                continue
            try:
                net = (ipaddress.ip_network(ip, strict=False) if "/" in ip
                       else ipaddress.ip_network(f"{ip}/24", strict=False))
                if net not in self._allowed_nets:
                    self._allowed_nets.append(net)
                self.facts.ips_seen.add(ip.split("/")[0])
                self.facts.add_host(ip.split("/")[0], t.get("name") or "")
            except ValueError:
                pass
        # authorized LAN scope (home-lab): the whole CIDR is fair game AND
        # out-of-scope private space becomes a hard deny — real ROE, not just
        # a prompt line. Without this seed the guard silently disables itself
        # on quests with no lab targets.
        scope = (self.ctx.get("quest", {}).get("scope") or "").strip()
        if scope:
            try:
                net = ipaddress.ip_network(scope, strict=False)
                if net not in self._allowed_nets:
                    self._allowed_nets.append(net)
                self.facts.ips_seen.add(scope.split("/")[0])
            except ValueError:
                pass
        esc = self.ctx.get("quest", {}).get("escalation", {})
        coach_cfg = self.cfg.get("coach", {})
        self.policy = Policy(
            esc,
            nudge_s=int(coach_cfg.get("nudge_after_s", 480)),
            hint_s=int(coach_cfg.get("hint_after_s", 900)),
            verbosity=coach_cfg.get("verbosity", "normal"),
            takeover_pace_s=int(coach_cfg.get("takeover_pace_s", 10)),
        )
        llm = self.cfg.get("llm", {})
        self.llm = LlmClient(
            llm.get("base_url", ""), llm.get("api_key", ""), llm.get("model", ""),
            temperature=float(llm.get("temperature", 0.4)),
            timeout_s=get_config().llm_timeout_s,
            reasoning=bool(llm.get("reasoning", True)),
            reasoning_effort=llm.get("reasoning_effort") or None,
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
        # commands the coach issued earlier — the backend records them, so a
        # restart can re-mark them; otherwise replayed coach commands would
        # count as trainee activity (idle detection + anti-loop guards break)
        coach_heads = [
            (str(c.get("command") or "")[:60] if isinstance(c, dict)
             else str(c)[:60])
            for c in (self.ctx.get("coach_commands") or [])]
        for ev in reversed(self.ctx.get("telemetry_tail", [])):
            payload = ev.get("payload") or {}
            if ev.get("kind") == "command":
                cmd = payload.get("command", "")
                if cmd:
                    self.state.add_command(
                        payload.get("ts", time.time()), cmd,
                        payload.get("cwd", ""),
                        from_coach=any(cmd[:60] == h for h in coach_heads))
                    expect_result = True
            elif ev.get("kind") == "command_result" and expect_result:
                if self.state.commands:
                    self.state.commands[-1].exit_code = int(
                        payload.get("exit_code", 0))
                expect_result = False
        # coach execs live in coach_actions, not telemetry (the pane has no
        # hook) — inject them too or the replayed command memory is empty
        # and ALREADY_DONE/RECON/FILES guards see nothing after a restart
        coach_entries = [c for c in (self.ctx.get("coach_commands") or [])
                         if isinstance(c, dict)]
        seen_heads = {c.command[:60] for c in self.state.commands}
        for c in reversed(coach_entries):
            cmd = str(c.get("command") or "")
            if not cmd or cmd[:60] in seen_heads:
                continue
            self.state.add_command(time.time(), cmd, from_coach=True)
            try:
                self.state.commands[-1].exit_code = (
                    int(c["exitcode"]) if c.get("exitcode") is not None else None)
            except (TypeError, ValueError):
                self.state.commands[-1].exit_code = None
            seen_heads.add(cmd[:60])
        # FactsDB rebuild: replayed command memory feeds the same extraction
        # paths live events use — guards, creds, hosts and files all survive
        # a restart. mark_run_exit confirms pending writes/runs in order.
        # Coach commands covered by coach_outputs are skipped here — their
        # write/run bookkeeping comes from observe_output below (one count).
        covered = {str(o.get("command") or "")
                   for o in (self.ctx.get("coach_outputs") or [])}
        for c in self.state.commands:
            if c.from_coach and c.command in covered:
                continue
            self.facts.observe_command(c.command)
            if c.exit_code is not None:
                self.facts.mark_run_exit(c.exit_code)
        # exec/type outputs (backend keeps them in CoachAction.result) add
        # parsed facts — ports, creds, hostnames — the command replay can't
        # see. Chronological replay keeps write/run bookkeeping ordered.
        for o in reversed(self.ctx.get("coach_outputs") or []):
            self.facts.observe_output(str(o.get("command") or ""),
                                      str(o.get("out") or ""),
                                      o.get("exitcode"))
            # seed the output-signature dedup — identical outputs after a
            # restart must hit "settled facts" immediately, not after two
            # more repeats (the guard's memory was process-local)
            if o.get("exitcode") == 0:
                _out = str(o.get("out") or "")
                if _out.strip():
                    sig = hashlib.sha1(
                        "\n".join(l.strip() for l in _out.splitlines()
                                  if l.strip())[:1500].encode()
                    ).hexdigest()[:12]
                    self._out_sigs[sig] = self._out_sigs.get(sig, 0) + 1
        # seed seen-flag evidence from past tool outputs — after a restart a
        # re-submit of an already-shown flag must not hit the unverified
        # challenge, and an invented value still gets caught
        for o in self.ctx.get("flag_outs") or []:
            for fv in FLAG_RE.findall(str(o)):
                self.facts.flag_seen(fv)
        # recorded submit outcomes survive restarts — without this every
        # re-attach sees the accepted flag as "unsubmitted" and resubmits
        # (s46 resubmitted flag-1 after every coach restart)
        for s in self.ctx.get("flag_submits") or []:
            if isinstance(s, dict) and s.get("value"):
                self.facts.flag_mark_submitted(
                    str(s["value"]), bool(s.get("correct")))
        # finished worker reports persist as agent-tagged messages — merge
        # them back so a restart doesn't orphan their findings (the roster
        # itself stays dead; knowledge, not tasks, is what survives)
        for wr in self.ctx.get("worker_reports") or []:
            if not isinstance(wr, dict):
                continue
            content = str(wr.get("content") or "")
            parsed = percept.parse_worker_report(content)
            if parsed:
                self.facts.apply_worker_report(
                    str(wr.get("agent") or "w?"), parsed)
            elif content:
                self.facts.apply_delta(
                    percept.parse_output("", content),
                    source=str(wr.get("agent") or "w?"))
        # intent memory: the agent's own roadmap + private notes survive
        # restarts via coach_actions — without this the model re-derives
        # its multi-step plan from scattered evidence after every restart
        self.state.plan = normalize_plan(self.ctx.get("plan") or [])
        # a restart doesn't make the plan stale — the staleness nudge only
        # fires when the MODEL hasn't refreshed in-session for a while
        self.state.plan_updated = time.time()
        self.state.notes = [str(n)[:300]
                            for n in self.ctx.get("coach_notes") or []][-8:]
        # stuck/idle clocks seed from the most RECENT liveness signal —
        # not blindly from started_at (a session parked in 'ready' for hours
        # then activated must not look stuck-since-forever)
        seeds = [_iso_to_epoch(s.get("started_at")),
                 _iso_to_epoch(s.get("ready_at")),
                 self.state.last_activity_ts]
        self.state.last_progress_ts = max((x for x in seeds if x), default=time.time())
        if self.state.last_activity_ts <= 0:
            self.state.last_activity_ts = self.state.last_progress_ts
        self._traj = _traj.for_session(self.sid)
        self._ready.set()
        # clear any stale roster a previous coach process left sticky — its
        # worker tasks died with it, the UI must not ghost them as running
        self._push_agents()
        self._task = asyncio.create_task(self._run())
        # a silently-dead run task is the worst failure mode — log its fate
        def _on_run_done(t: asyncio.Task) -> None:
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                exc = "cancelled"
            asyncio.get_event_loop().call_soon(
                lambda: log.info("coach run task ended",
                                 session=self.sid, outcome=repr(exc)))
        self._task.add_done_callback(_on_run_done)
        await log.ainfo("coach attached", session=self.sid,
                        autonomy=self.state.autonomy_level)
        await self._maybe_welcome()
        return True

    async def stop(self) -> None:
        self._stop.set()
        self._kill_all_workers()
        if self._traj:
            self._traj.close()
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
            takeover_pace_s=int(cc.get("takeover_pace_s", 10)),
        )
        global_on = bool(cc.get("enabled", True))
        s = self.ctx.get("session", {})
        self.state.coach_enabled = bool(s.get("coach_enabled", True)) and global_on
        llm = cfg.get("llm", {})
        if (llm.get("base_url"), llm.get("api_key"), llm.get("model"),
                llm.get("temperature"), llm.get("reasoning"),
                llm.get("reasoning_effort")) != (
                old_llm.get("base_url"), old_llm.get("api_key"),
                old_llm.get("model"), old_llm.get("temperature"),
                old_llm.get("reasoning"), old_llm.get("reasoning_effort")):
            new = LlmClient(
                llm.get("base_url", ""), llm.get("api_key", ""),
                llm.get("model", ""),
                temperature=float(llm.get("temperature", 0.4)),
                timeout_s=get_config().llm_timeout_s,
                reasoning=bool(llm.get("reasoning", True)),
                reasoning_effort=llm.get("reasoning_effort") or None)
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
        self.state.subagents_enabled = bool(
            s.get("subagents_enabled", self.state.subagents_enabled))
        # resync is the drift-repair path — the same kill rule the live
        # autonomy/subagents handlers enforce must apply here too, or a
        # dropped event leaves workers holding exec rights on Kali
        if (self.state.autonomy_level < 4
                or not self.state.subagents_enabled):
            self._kill_all_workers()
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
                await self._drain_queue(reflect)
                if time.monotonic() >= self._next_reflect:
                    await self._reflect_tick(reflect)
            except TimeoutError:
                try:
                    await self._reflect_tick(reflect)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    await log.aexception("reflect tick failed", error=str(e))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await log.aexception("coach event error", error=str(e))

    async def _drain_queue(self, reflect_s: float = 60.0, cap: int = 128) -> None:
        """Process queued events without blocking — keeps telemetry, state
        transitions and pending chat fresh while a turn chain is running."""
        drained = 0
        while drained < cap:
            try:
                await self._handle_event(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
            drained += 1
            if drained % 64 == 0 and time.monotonic() >= self._next_reflect:
                await self._reflect_tick(reflect_s)

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
                # exec_in_kali self-records at dispatch — a telemetry echo of
                # the same line (if the pane ever gets hook coverage) must
                # not add a duplicate
                if not self._is_coach_command(cmd):
                    self.state.add_command(
                        payload.get("ts", time.time()), cmd,
                        payload.get("cwd", ""), payload.get("exit_code"))
                    self.facts.observe_command(cmd)
                for cid in self.matcher.check(cmd):
                    if cid not in self.state.checkpoints_hit:
                        self.state.checkpoints_hit.add(cid)
                        self.state.progress()
                        await self.client.mark_checkpoint(self.sid, cid)
                        await self._quick_ack(
                            f"Checkpoint: **{self.matcher.name_for(cid)}** — logged.")
            elif kind == "command_result":
                code = int(payload.get("exit_code", 0))
                self.state.mark_exit(code)
                self.facts.mark_run_exit(code)
            # heartbeats & other kinds → ignored entirely

        # path 2: session/user signals
        elif topic.startswith("session."):
            if etype == "state":
                self.state.state = data.get("state", self.state.state)
                if data.get("state") == "solved":
                    await self._on_solved()
                elif data.get("state") == "ready":
                    await self._maybe_welcome()
                elif (data.get("state") == "active"
                        and self.state.autonomy_level >= 4):
                    # session just activated at takeover — start the agent
                    # loop now, not at the next reflect tick
                    self._next_reflect = min(self._next_reflect,
                                             time.monotonic() + 1)
            elif etype == "autonomy":
                # live level switch (/autonomy in chat or the UI toggle) —
                # resync-only would leave the coach on the old level until a
                # WS reconnect; tools_for_level + policy read this field
                prev = self.state.autonomy_level
                try:
                    level = int(data.get("level") or prev)
                except (TypeError, ValueError):
                    level = prev
                self.state.autonomy_level = level
                if "session" in self.ctx:
                    self.ctx["session"]["autonomy_level"] = level
                if level < 4:
                    # downgrade cuts worker privileges mid-flight — stop them
                    # (ROE: they hold exec rights on the trainee's machine)
                    self._kill_all_workers()
                if (level >= 4 > prev
                        and self.state.state == "active"):
                    # switched INTO takeover while the session runs — the
                    # agent should start working almost immediately
                    self._next_reflect = min(self._next_reflect,
                                             time.monotonic() + 1)
            elif etype == "subagents":
                # live subagent toggle (/subagents or the UI chip)
                enabled = bool(data.get("enabled"))
                self.state.subagents_enabled = enabled
                if "session" in self.ctx:
                    self.ctx["session"]["subagents_enabled"] = enabled
                if not enabled:
                    self._kill_all_workers()
            elif etype == "coach_enabled":
                # live pause/resume — lands immediately via WS, not on the
                # next resync. Pause kills workers too: an idle parent with
                # exec-armed workers isn't paused at all.
                enabled = bool(data.get("enabled"))
                if "session" in self.ctx:
                    self.ctx["session"]["coach_enabled"] = enabled
                global_on = bool(
                    self.cfg.get("coach", {}).get("enabled", True))
                was = self.state.coach_enabled
                self.state.coach_enabled = enabled and global_on
                if not self.state.coach_enabled:
                    self._kill_all_workers()
                elif not was and self.state.state == "active":
                    # resume → think soon instead of waiting out the interval
                    self._next_reflect = min(self._next_reflect,
                                             time.monotonic() + 1)
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
        self.state.operator_directive = content[:600]
        self.state.operator_directive_ts = time.time()
        if not self._chat_task or self._chat_task.done():
            self._chat_task = asyncio.create_task(self._chat_debounced())

    async def _chat_debounced(self) -> None:
        try:
            await asyncio.sleep(CHAT_DEBOUNCE_S)
            if not self.state.pending_chat:
                return
            text = "\n".join(self.state.pending_chat)
            self.state.pending_chat.clear()
            await asyncio.wait_for(self._answer_chat(text),
                                   timeout=LLM_TURN_BUDGET_S)
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
        await log.ainfo("reflect decision", session=self.sid,
                        may=decision.may_proactive, reason=decision.reason,
                        stage=decision.stage,
                        idle_s=int(self.state.idle_s()),
                        stuck_s=int(self.state.stuck_s()))
        if not decision.may_proactive:
            return
        budget = int(self.cfg.get("coach", {}).get("action_budget", 50))
        try:
            # a single wedged turn (stuck HTTP call, lock holder that never
            # returns) must not take the whole session loop down with it
            t0 = time.monotonic()
            await asyncio.wait_for(
                self._llm_turn(
                    build_context_msg(self.ctx, self.state, decision.reason,
                                      decision.urgency, stage=decision.stage,
                                      action_budget=budget,
                                      facts=self.facts),
                    proactive=True),
                timeout=LLM_TURN_BUDGET_S)
            # L4 stall correction: a proactive turn that produced NO real work
            # (chat-only announce, bare `none`, denied write) gets ONE bounded
            # retry — the rebuilt context now carries STALL_ALERT naming the
            # failure. streak>0 post-turn ⟺ this turn did no work (a worked
            # turn resets it). Skipped when the action budget is exhausted —
            # every further exec would be denied anyway.
            # interactive fast-path: the pane holds a program waiting for
            # input (ssh password, menu, remote shell). The normal ~90s tick
            # is SLOWER than LoginGraceTime — and a full remote command
            # sequence (whoami, sudo -l, privesc, flags) at 90s/step takes
            # forever. Chain bounded follow-up turns while the pane stays
            # interactive or the model keeps stalling; each is still capped
            # by this tick's time budget and the exec budget.
            for _retry in range(4):
                left = LLM_TURN_BUDGET_S - (time.monotonic() - t0)
                if not (self.state.autonomy_level >= 4
                        and (self.state.proactive_streak > 0
                             or self._pane_interactive)
                        and self.state.exec_count < budget and left > 30):
                    break
                why = ("interactive input pending"
                       if self._pane_interactive else "stall correction")
                await asyncio.wait_for(
                    self._llm_turn(
                        build_context_msg(self.ctx, self.state, why,
                                          decision.urgency,
                                          stage=decision.stage,
                                          action_budget=budget,
                                          facts=self.facts),
                        proactive=True),
                    timeout=left)
            # continuous agent loop: the last chain DID work — keep the
            # pipeline flowing at takeover pace instead of the reflect
            # interval, so an L4 run doesn't stall ~60s between chains
            if (self.state.autonomy_level >= 4
                    and self.state.proactive_streak == 0):
                self._next_reflect = time.monotonic() + float(
                    self.cfg.get("coach", {}).get("takeover_pace_s", 10))
        except TimeoutError:
            await log.aexception("reflect turn exceeded budget — cancelled",
                                 session=self.sid, budget_s=LLM_TURN_BUDGET_S)
            return

    async def _answer_chat(self, user_msg: str) -> None:
        if not self.llm or not self.state.coach_enabled:
            return
        await asyncio.wait_for(
            self._llm_turn(chat_prompt(user_msg), force_reply=True,
                           record_user=user_msg),
            timeout=LLM_TURN_BUDGET_S)

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
        """Draft-safety wrapper — EVERY exit path of a turn (normal return,
        dispatch exception, cancel at the turn budget) must close the UI's
        streaming draft, or an open 'thinking' bubble ghosts forever."""
        self._turn_deadline = time.monotonic() + LLM_TURN_BUDGET_S
        try:
            return await self._llm_turn_body(
                user_msg, force_reply=force_reply, proactive=proactive,
                record_user=record_user)
        finally:
            self._turn_deadline = None
            await self._close_draft()

    async def _close_draft(self) -> None:
        """Relay done for the in-flight draft (idempotent — the persisted
        message also removes it via meta.draft_id) and clear the slot.
        Only sent when deltas actually streamed, or the UI would flash an
        empty bubble for a draft it never saw."""
        did, sent = self._active_draft, self._draft_pushed
        self._active_draft = None
        self._draft_pushed = False
        if did and sent:
            with contextlib.suppress(Exception):
                await self.client.stream_draft(self.sid, did, "", done=True)

    async def _llm_turn_body(self, user_msg: str, *, force_reply: bool = False,
                             proactive: bool = False,
                             record_user: str | None = None) -> bool:
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
            self._history = self._trim_history()
        tools_active = (bool(self.cfg.get("llm", {}).get("use_tools", True))
                        and "no_tools" not in getattr(self.llm, "_compat", set()))
        async with self._llm_lock:
            messages = [{"role": "system",
                         "content": system_prompt(tools_active)}]
            messages += wire_history(self._history, tools_active)
            messages.append({"role": "user", "content": user_msg})
            # streaming draft: deltas flow to the UI while the model writes;
            # the first real message this turn posts carries meta.draft_id so
            # the draft bubble is replaced atomically
            self._draft_seq += 1
            draft_id = f"{self.sid}d{self._draft_seq}"
            self._active_draft = draft_id
            self._draft_used = False
            self._draft_pushed = False
            self._turn_reasoning = ""
            pushed = False
            last_push = 0.0
            kind = "nudge" if proactive else "message"

            async def on_delta(cum: str, reasoning: str = "") -> None:
                nonlocal pushed, last_push
                if not get_config().llm_stream:
                    return
                now = time.monotonic()
                if pushed and now - last_push < 0.12:
                    return  # throttle — LAN relay, ~8 msgs/s is plenty
                pushed = True
                last_push = now
                self._draft_pushed = True
                await self.client.stream_draft(
                    self.sid, draft_id, cum, reasoning=reasoning, kind=kind)

            spoke = False
            worked = False
            t0 = time.monotonic()
            chain_max = int(self.cfg.get("coach", {}).get(
                "takeover_chain_max", 12))
            chain_len = 0
            while True:
                pushed = False
                last_push = 0.0   # each sub-response streams its own draft
                # rebuilt per sub-call: an autonomy/subagents switch mid-chain
                # (drained between calls) narrows/widens the toolset at once
                tools = (tools_for_level(
                    self.state.autonomy_level,
                    subagents=self.state.subagents_enabled)
                    if tools_active else None)
                try:
                    resp = await self.llm.chat(messages, on_delta=on_delta,
                                               tools=tools)
                except (LlmError, httpx.HTTPError) as e:
                    # one quiet retry — a slow/flaky endpoint shouldn't kill
                    # the turn outright; the turn budget keeps worst-case
                    # bounded
                    await log.awarning("llm call failed, retrying once",
                                       error=str(e))
                    try:
                        resp = await self.llm.chat(messages, tools=tools)
                    except (LlmError, httpx.HTTPError) as e2:
                        await log.awarning("llm call failed", error=str(e2))
                        return False
                chain_len += 1
                self._turn_reasoning = (resp.get("reasoning") or "").strip()
                usage = (resp.get("raw") or {}).get("usage") or {}
                self.usage["tokens"] += int(usage.get("total_tokens", 0))
                await log.ainfo("llm turn", session=self.sid,
                                tools=tools_active,
                                via_tool_calls=bool(resp.get("tool_calls")),
                                compat=sorted(getattr(self.llm, "_compat", ())),)
                # fire-and-forget usage row for the stats page — never block
                # the turn
                asyncio.create_task(self.client.report_llm_usage(
                    self.sid, self.llm.model, "reflect" if proactive else "chat",
                    resp.get("usage"), resp.get("latency_ms")))
                call_results: dict[str, str] = {}
                acts: list[dict] = []
                await log.ainfo("llm actions", session=self.sid,
                                proactive=proactive,
                                actions=[a.get("type") for a in resp["actions"]])
                try:
                    for a in resp["actions"]:
                        # model "reasoning notes" become working memory for
                        # later turns
                        if a.get("type") == "none" and a.get("reason"):
                            note_txt = str(a["reason"])[:300]
                            self.state.notes.append(note_txt)
                            self.state.notes = self.state.notes[-8:]
                            # persist — notes are working memory that must
                            # survive a coach restart like everything else
                            asyncio.create_task(self.client.log_action(
                                self.sid, "note",
                                {"text": note_txt, "agent": "main"}, {}))
                        did, res = await self._dispatch(a, proactive=proactive)
                        spoke |= did
                        if cid := a.get("_call_id"):
                            call_results[cid] = res
                        if did and a.get("type") in ("exec_in_kali", "type_in_pane",
                                                     "submit_flag", "check_flag",
                                                     "wait"):
                            worked = True
                        arg = (a.get("command") or a.get("text")
                               or a.get("content") or a.get("value")
                               or a.get("task") or a.get("why")
                               or a.get("reason") or "")
                        acts.append({"t": a.get("type"),
                                     "arg": str(arg)[:200],
                                     "res": (res or "")[:240],
                                     "denied": str(res or "").startswith(
                                         "denied:")})
                finally:
                    # whatever happened mid-dispatch — no stale 'working' chip
                    await self.client.send_activity(self.sid, active=False,
                                                    agent="main")
                self._traj.record(
                    kind="turn", proactive=proactive, chain=chain_len,
                    reason=str(user_msg)[:160], actions=acts,
                    tokens=int(usage.get("total_tokens", 0)),
                    facts={k: len(v) for k, v in
                           (("hosts", self.facts.hosts),
                            ("creds", self.facts.creds),
                            ("files", self.facts.files),
                            ("flags", self.facts.flags)) if v})
                calls = resp.get("tool_calls") or []
                if calls:
                    # replay the exchange faithfully: the model sees its own
                    # tool calls plus EVERY call's result (pairing rule —
                    # strict templates reject a tool_call left without its
                    # tool reply). Fed back via `messages` for the next
                    # sub-call AND persisted in _history for later turns.
                    chat_text = "\n".join(
                        a.get("content", "")[:900] for a in resp["actions"]
                        if a.get("type") in ("send_chat", "offer_hint",
                                             "suggest_command") and a.get("content"))
                    messages.append({
                        "role": "assistant",
                        "content": chat_text or None,
                        "tool_calls": calls,
                    })
                    self._history.append(dict(messages[-1]))
                    for i, call in enumerate(calls):
                        cid = call.get("id") or f"call_{i}"
                        tool_msg = {
                            "role": "tool", "tool_call_id": cid,
                            "content": call_results.get(
                                cid, "error: invalid or dropped arguments")[:2000],
                        }
                        messages.append(tool_msg)
                        self._history.append(dict(tool_msg))
                    self._history = self._trim_history()
                # agentic chain: the model issued calls with real effects —
                # feed their results straight back so act→observe→act runs
                # at LLM cadence instead of waiting for the next reflect tick
                if not calls or not any(
                        a.get("type") in _CHAIN_TOOLS for a in resp["actions"]):
                    break  # model chose to talk/pause — normal exit
                if (chain_len >= chain_max
                        or time.monotonic() - t0 > LLM_TURN_BUDGET_S - 30
                        or self._budget_exceeded()
                        or (proactive and self.state.state != "active")):
                    break
                # pull queued telemetry/state/chat BEFORE the next sub-call —
                # keeps command memory fresh and lets trainee chat preempt
                await self._drain_queue()
                if self.state.pending_chat:
                    break  # operator message wins — release the llm lock
            if worked:
                # real work happened — this turn is progress, not an
                # unanswered nudge; don't let it feed the backoff streak
                self.state.proactive_streak = 0
            elif proactive and (spoke or self.state.autonomy_level >= 4):
                # L4: ANY turn without real work is a stall (chat-only AND
                # silent 'none' turns alike) — the model gets no trainee
                # reply to react to, it must see the stall counted.
                self.state.proactive_streak += 1
            if not spoke and force_reply:
                text = resp["content"][:1500]
                await self.client.send_chat(self.sid, text, meta=self._draft_meta())
                self._record_reply(text)
                spoke = True
            if chain_len > 1:
                await log.ainfo("llm turn done", session=self.sid,
                                chain_len=chain_len)
            return spoke

    def _record_reply(self, text: str) -> None:
        self._history.append({"role": "assistant", "content": text[:900]})
        self._history = self._trim_history()

    def _trim_history(self) -> list[dict]:
        """trim_history + rolling summary: whatever falls off the front is
        distilled to one line in state.earlier — long-horizon L4 runs keep a
        trace of their early turns instead of a hard cut (the 'no growing
        chat log' rule doesn't have to mean 'no memory of it')."""
        before = self._history
        after = trim_history(before, HISTORY_CAP)
        dropped = len(before) - len(after)
        for m in before[:dropped]:
            role = m.get("role")
            if role == "tool":
                line = f"saw: {(m.get('content') or '')[:90]}"
            elif role == "assistant" and m.get("tool_calls"):
                tools = ",".join(
                    (c.get("function") or {}).get("name") or "?"
                    for c in m["tool_calls"][:4])
                line = f"acted: {tools}"
                if m.get("content"):
                    line += f" ({m['content'][:50]})"
            elif role == "assistant":
                line = f"said: {(m.get('content') or '')[:90]}"
            else:
                line = f"trainee: {(m.get('content') or '')[:90]}"
            self.state.earlier.append(line[:120])
        self.state.earlier = self.state.earlier[-10:]
        return after

    def _draft_meta(self) -> dict:
        """Attach the active draft_id (+ turn reasoning) to the FIRST message
        this turn posts — the UI swaps the streaming bubble for the real
        message by draft_id; reasoning persists as a collapsed 'thinking'
        section inside that final bubble."""
        meta: dict = {}
        if self._active_draft and not self._draft_used:
            self._draft_used = True
            meta["draft_id"] = self._active_draft
        if meta and self._turn_reasoning:
            meta["reasoning"] = self._turn_reasoning[:3500]
        return meta

    def _msg_meta(self, window: str | None) -> dict:
        """Meta for dispatch-posted chat lines. Worker paths tag meta.agent
        (the UI routes them into that agent's feed) plus their own turn's
        reasoning — never the parent's draft meta, which would graft a
        worker message onto the parent's draft bubble."""
        if not window:
            return self._draft_meta()
        meta: dict = {"agent": window}
        if r := self._worker_reasoning.pop(window, None):
            meta["reasoning"] = r[:3500]
        return meta

    def _push_agents(self) -> None:
        """Push the worker roster to the UI's agent chips — fire-and-forget;
        an empty roster after a coach restart clears stale chips (worker
        tasks died with the previous process anyway)."""
        now = time.monotonic()
        agents = [{"id": w.id, "task": w.task[:200], "status": w.status,
                   "actions": w.actions,
                   "elapsed": round(now - w.started, 1)}
                  for w in sorted(self._workers.values(), key=lambda x: x.id)]
        asyncio.create_task(self.client.send_agents(self.sid, agents))

    # ---------- action dispatch ----------

    _FLAG_PLACEHOLDER_RE = re.compile(
        r"^pentrAIn\{(?:\.{2,}|x{3,}|example|flag|your[-_ ]?flag.*|"
        r"flag[-_ ]?here|<.*>)\}$", re.IGNORECASE)

    async def _scan_flags(self, out: str, cmd: str = "",
                          window: str | None = None) -> str:
        """flag-on-sight: a pentrAIn{...} in tool output IS the flag —
        per-session values make guessing impossible, so the only correct
        move is submit_flag NOW. First sight gets a directive; the SECOND
        sight means the model is re-reading instead of submitting (seen
        live: 5 identical flag re-reads), so we submit it ourselves —
        real flags are correct anyway, wrong submits are already counted
        by the backend either way."""
        note = ""
        # IPs observed in output become allowed targets (pivot-safe) — kept
        # here as well as in observe_output so a bare _scan_flags call (tests,
        # legacy paths) still relaxes the foreign-ip guard correctly. IPs
        # already present in the command are intent, not discovery: echoing
        # them back in an error must not whitelist a hallucinated target.
        cmd_ips = set(self._IP_RE.findall(cmd or ""))
        self.facts.ips_seen.update(
            ip for ip in self._IP_RE.findall(out or "") if ip not in cmd_ips)
        # discovered subnets (routing table, ifconfig on a compromised host)
        # authorize the whole net — the multi-segment pivot case
        for cidr in self._CIDR_RE.findall(out or ""):
            try:
                net = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            if (net.prefixlen < 8 or net.is_loopback or net.is_multicast
                    or not net.is_private):
                continue
            if all(net not in a for a in self._allowed_nets) \
                    and net not in self._allowed_nets:
                self._allowed_nets.append(net)
        for fv in set(FLAG_RE.findall(out or "")):
            if self._FLAG_PLACEHOLDER_RE.match(fv):
                continue
            n = self.facts.flag_seen(fv)
            if n == 1:
                if window:
                    # workers can't submit_flag — tell them to hand the flag
                    # to the parent via their report instead of burning a
                    # turn on a denied tool call
                    note += (f"\nFLAG CAPTURED: {fv} — include it verbatim "
                             f"in your report so the parent coach can "
                             f"submit it. Do not re-run commands to "
                             f"re-confirm it.")
                else:
                    note += (f"\nFLAG CAPTURED: {fv} — call submit_flag with "
                             f"it NOW (flag values are per-session; a wrong "
                             f"submit is impossible). Do not re-run commands "
                             f"to re-confirm it.")
            elif not self.facts.flags[fv].submitted:
                try:
                    r = await self.client.submit_flag(self.sid, fv)
                except (TimeoutError, httpx.HTTPError) as e:
                    r = {"error": f"transport {type(e).__name__}"}
                ok = bool(r.get("correct"))
                self.facts.flag_mark_submitted(fv, ok)
                if ok:
                    verdict = "correct — flag solved"
                    if r.get("all_solved"):
                        verdict += "; all_solved — quest complete"
                else:
                    verdict = f"rejected ({r.get('error') or 'wrong value'})"
                note += (f"\nAUTO-SUBMITTED {fv} → {verdict}. It appeared "
                         f"{n}x in output — re-reading is pure waste, move "
                         f"on to the NEXT objective.")
                await self.client.send_chat(
                    self.sid,
                    f"Auto-submitted flag `{fv}` (seen {n}x) → **{verdict}**",
                    kind="action_report", meta=self._msg_meta(window))
            else:
                prev = ("accepted" if self.facts.flags[fv].accepted
                        else "rejected")
                note += (f"\n{fv} — submission already attempted ({prev}); "
                         f"stop re-reading it and move on.")
        return note

    _IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    _CIDR_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b")

    def _foreign_ip(self, cmd: str) -> str | None:
        """Private/link-local literal that's neither inside a target /24 nor
        seen in earlier output. Public IPs pass (internet uplink); observed
        IPs pass (pivot/discovered hosts); invented ones are denied — they
        hang every connect (session 31: model merged kali's 10.1.10.5 into
        10.42.0.5 and burned ~10 turns on it)."""
        if not self._allowed_nets:
            return None                     # no baseline — can't judge foreign
        for lit in self._IP_RE.findall(cmd):
            try:
                ip = ipaddress.ip_address(lit)
            except ValueError:
                continue
            if ip.is_loopback or not (ip.is_private or ip.is_link_local):
                continue
            if lit in self.facts.ips_seen:
                continue
            if any(ip in n for n in self._allowed_nets):
                continue
            return lit
        return None

    def _denial_match(self, cmd: str) -> str | None:
        """Exec cmd vs. settled denial facts — the FIRST matching dead end
        or None. Conservative: only fires on same evidence, never fuzzy.
          unreachable:{ip}@{vantage} — same ip, same vantage (a different
            pivot may still route; e.g. unreachable-from-shop01 does not
            block a direct Kali probe)
          denied:{svc}-{user}@{h}     — same binary + user + pivot host
          denied:sudo|docker@{h}      — same keyword + pivot host
        ({svc}-auth denials are NOT matched: they don't record which cred
        failed, and the working pivot uses the same svc+host pair — an
        ssh-auth@shop01 entry would brick every valid sshpass pivot.)"""
        if not self.facts.denials:
            return None
        ssh = _USER_AT_HOST.search(cmd or "")
        pivot = ssh.group(2) if ssh else "kali"
        for dn in self.facts.denials:
            if dn.startswith("unreachable:"):
                rest = dn.split(":", 1)[1]
                ip, _, vantage = rest.rpartition("@")
                if ip and ip in cmd and vantage == pivot:
                    return dn
                continue
            m = _DENIAL_FORM.match(dn)
            if not m:
                continue
            svc, user, host = m.group(1), m.group(2), m.group(3)
            if host != pivot or user == "auth" \
                    or not re.search(rf"\b{re.escape(svc)}\b", cmd or ""):
                continue
            if user is None or re.search(rf"\b{re.escape(user)}\b",
                                         cmd or ""):
                return dn
        return None

    async def _dispatch(self, a: dict, *, proactive: bool = False,
                        window: str | None = None) -> tuple[bool, str]:
        """Guard-denial audit: every 'denied:' result self-reports to the
        backend (exec/type denials that never reach the API would otherwise
        be invisible to agent-metrics). Fire-and-forget, never blocks."""
        spoke, result = await self._dispatch_inner(
            a, proactive=proactive, window=window)
        if isinstance(result, str) and result.startswith("denied:"):
            args = {k: v for k, v in (a or {}).items()
                    if k in ("command", "text", "task", "worker_id",
                             "value", "flag_key") and isinstance(v, str)}
            self._traj.record(kind="denial", tool=a.get("type"),
                              args=args, reason=result[7:].strip()[:300])
            report = getattr(self.client, "log_denial", None)
            if report:
                async def _audit() -> None:
                    try:
                        await report(self.sid, str(a.get("type") or "?"),
                                     args, result[7:].strip())
                    except Exception as e:   # audit must never break a turn
                        await log.adebug("denial audit failed", error=str(e))
                asyncio.create_task(_audit())
        return spoke, result

    async def _dispatch_inner(self, a: dict, *, proactive: bool = False,
                              window: str | None = None) -> tuple[bool, str]:
        """Execute one LLM action under autonomy/budget gates.
        Returns (visible_to_trainee, result_text) — the result text becomes the
        `tool` reply the model sees in history, so EVERY action reports an
        outcome, including denied ones. `window` routes exec/type into a
        worker's own tmux window (subagent mode)."""
        t = a.get("type")
        level = self.state.autonomy_level
        spoke = False
        result = "ok"
        if t != "wait":
            self._wait_streak[window or "main"] = 0

        # workers are exec-only — a model emitting an unoffered tool through a
        # worker context gets a hard deny (defense-in-depth; the tool schema
        # already prevents it, this covers drift/compat endpoints). The deny
        # is part of the worker's story — its feed should show it
        if window and t not in WORKER_TOOL_NAMES:
            result = ("denied: workers can only run exec_in_kali / "
                      "type_in_pane — report findings via your last "
                      "message, the parent coach relays them")
            await self.client.send_chat(
                self.sid, f"Denied: `{t}` — workers may only exec/type",
                kind="action_report", meta=self._msg_meta(window))
            return spoke, result

        if t == "send_chat":
            content = (a.get("content") or "").strip()[:2000]
            if not content:
                return spoke, "error: empty content"
            kind = "nudge" if proactive else "message"
            await self.client.send_chat(self.sid, content, kind=kind,
                                        meta=self._draft_meta())
            self._record_reply(content)
            spoke, result = True, "delivered"
        elif t == "offer_hint":
            content = (a.get("content") or "").strip()[:2000]
            if not content:
                return spoke, "error: empty content"
            level = min(3, max(1, int(a.get("level") or 1)))
            await self.client.send_chat(self.sid, content, kind="hint",
                                        meta={"level": level, **self._draft_meta()})
            self._record_reply(content)
            self.state.last_hint_ts = time.time()
            spoke, result = True, "delivered"
        elif t == "suggest_command":
            cmd = (a.get("command") or a.get("content") or "").strip()
            if level < 3:
                result = f"denied: autonomy level {level} < 3"
            elif level >= 4:
                # full-auto mode has nobody to click the confirm chip —
                # bounce it back so the model exec's directly next call
                result = "denied: at autonomy 4 run it via exec_in_kali directly"
            elif not cmd:
                result = "error: empty command"
            else:
                await self.client.suggest_command(
                    self.sid, cmd, a.get("why", ""))
                # remember we asked — the trainee may confirm or reject
                self._record_reply(f"[suggested command] `{cmd}` — {a.get('why', '')}")
                spoke, result = True, "queued for trainee confirmation"
        elif t == "exec_in_kali":
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            else:
                budget = int(self.cfg.get("coach", {}).get("action_budget", 50))
                grace = int(self.cfg.get("coach", {}).get("action_grace", 10))
                grace_note = ""
                n_over = self.state.exec_count - budget
                if n_over >= grace:
                    result = ("denied: action budget exhausted (incl. "
                              f"{grace} grace) — raise coach.action_budget "
                              "in Settings to continue")
                else:
                    if n_over >= 0:
                        # soft-cap: finish what is open, don't start new
                        # exploration lines (s46 froze mid-flag-4-chain)
                        if not self.state._grace_noted:
                            self.state._grace_noted = True
                            await self.client.send_chat(
                                self.sid,
                                "Coach action budget reached — grace window "
                                f"({grace} execs) to finish pending chains. "
                                "Raise coach.action_budget to continue.",
                                kind="nudge")
                        grace_note = (
                            f"GRACE {n_over + 1}/{grace}: budget exceeded — "
                            "finish pending chains (read pending loot, "
                            "submit flags, write report); no new "
                            "exploration.\n")
                    cmd = (a.get("command") or a.get("content", "")).strip()
                    if not cmd:
                        return spoke, "error: empty command"
                    # denied-facts guard: evidence already settled this exact
                    # path (same cred+svc+host, same unreachable target) — the
                    # facts render shows it, but renders don't STOP retries
                    # (s46: mysql root+DEPLOY_PASS denied at 21:14, retried
                    # verbatim at 00:37 after a restart)
                    if dn := self._denial_match(cmd):
                        return spoke, (f"denied: prior evidence — {dn}. "
                                       "Try a different user, host, "
                                       "or vector.")
                    # rewrite guard: a solver that was written ≥2× and never
                    # ran (or ran clean) does NOT need another version — the
                    # model 'perfects' scripts forever otherwise. Deny before
                    # typing anything; a failed run unlocks the next rewrite.
                    wm = WRITE_RE.search(cmd)
                    if wm:
                        path = wm.group(1) or wm.group(3)
                        ff = self.facts.files.get(path)
                        n = ff.writes if ff else 0
                        last = ff.last_exit if ff else None
                        # externally-executed files (proven via a caps: fact,
                        # e.g. root cron) can't be "RUN" by us — demanding
                        # `python3 -u <path>` for a cron script is a dead end
                        external = any(path in c for c in self.facts.caps)
                        if (not external and n >= 2
                                and (last is None or last == 0)):
                            why = ("ran without error" if last == 0
                                   else "was never executed")
                            await log.ainfo("rewrite denied", session=self.sid,
                                            path=path, writes=n, cmd=cmd[:120])
                            return spoke, (
                                f"denied: {path} was already written {n}x and "
                                f"{why} — RUN it now (python3 -u {path}). "
                                f"Another rewrite is only useful after a "
                                f"failed run.")
                    # read-loop guard: re-reading the same file produces
                    # identical output — settled facts the model keeps
                    # re-deriving (seen live: 6x `cat nmap.txt | grep …`
                    # variants instead of connecting to the found service).
                    # The output-sig NOTE below is only a hint — the 4th
                    # read of the SAME path is denied before typing.
                    read_tgt = facts_mod.read_target(cmd)
                    if read_tgt:
                        rf = self.facts.files.get(read_tgt)
                        n = rf.reads if rf else 0
                        if n >= 3:
                            await log.ainfo("reread denied",
                                            session=self.sid, path=read_tgt,
                                            reads=n, cmd=cmd[:120])
                            return spoke, (
                                f"denied: {read_tgt} was already read "
                                f"{n}x with the same result — its contents "
                                f"are settled facts (see ALREADY_DONE). "
                                f"Take a DIFFERENT action toward the flag: "
                                f"connect to a discovered service, use "
                                f"credentials you found, or submit a flag.")
                    bad_ip = self._foreign_ip(cmd)
                    if bad_ip:
                        known = [f"{t.get('name')}={t.get('ip')}"
                                 for t in (self.ctx.get("quest", {}).get(
                                     "targets") or []) if t.get("ip")]
                        await log.ainfo("foreign ip denied", session=self.sid,
                                        ip=bad_ip, cmd=cmd[:120])
                        return spoke, (
                            f"denied: {bad_ip} is no known target — connects "
                            f"to it hang and eat the pane. KNOWN TARGETS: "
                            f"{'; '.join(known) or '(resolve names via getent)'}. "
                            f"A host is only allowed once its IP appears in "
                            f"tool output (scan result, getent, logs).")
                    # mark BEFORE the call so telemetry echo is recognized as ours
                    self._coach_cmds.append((cmd, time.time()))
                    where = f"[{window}] " if window else ""
                    await self.client.send_activity(
                        self.sid, f"{where}typing `{cmd[:110]}` in Kali",
                        agent=window or "main")
                    try:
                        res = await self.client.exec_in_kali(self.sid, cmd,
                                                             window=window)
                    except (TimeoutError, httpx.HTTPError) as e:
                        # backend/qga hiccup — surface as a tool RESULT so the
                        # model can check/retry next turn instead of the whole
                        # turn dying on an unhandled transport error
                        self._coach_cmds.pop()
                        return spoke, (
                            f"error: exec transport failed "
                            f"({type(e).__name__}) — the command may still be "
                            f"running on the pane; probe before re-running")
                    typed = False
                    if res.get("status") == "denied" or res.get("error") or res.get("busy"):
                        # never actually typed → a stale entry could mislabel a
                        # user-typed identical command
                        self._coach_cmds.pop()
                    else:
                        self.state.exec_count += 1
                        typed = True
                    out = (res.get("out") or res.get("err") or res.get("error") or "")
                    code = res.get("exitcode")
                    # interactive-program tracking: a fresh busy pane means a
                    # prompt (password/menu) may be ticking — the follow-up
                    # re-turn in _reflect_tick must come BEFORE ssh's
                    # LoginGraceTime kills the attempt. Workers handle their
                    # own window's busy state via res.busy in their loop.
                    if window is None:
                        if res.get("busy") or res.get("timed_out"):
                            self._pane_interactive = True
                        elif code is not None:
                            self._pane_interactive = False
                    if typed:
                        # the pentrain-coach pane is NOT covered by the shell
                        # telemetry hook — record our own exec so ALREADY_DONE
                        # and RECON_SATURATED see it (without this the model
                        # has zero command memory and re-scans blind)
                        self.state.add_command(time.time(), cmd,
                                               from_coach=True)
                        self.state.commands[-1].exit_code = code
                        # perceptor: normalize the model-facing reply and feed
                        # the facts store (ports/creds/hosts/files) in one pass
                        result = (percept.normalize(
                            cmd, out, code,
                            timed_out=bool(res.get("timed_out"))).reply
                            or "still running")
                        self.facts.observe_output(cmd, out, code)
                    elif code is None:
                        err_hint = res.get("err") or ""
                        if err_hint and err_hint not in out:
                            result = f"{out[:1500]}\n[{err_hint}]"[:1900]
                        else:
                            result = out[:1900] or "still running"
                        # bounced/denied — the command never ran, but the pane
                        # snapshot can still show a foreground program's
                        # findings; parse facts without run/write bookkeeping
                        if out:
                            self.facts.apply_delta(
                                percept.parse_output(
                                    cmd, percept.strip_ansi(out)))
                    else:
                        result = f"{out[:1900]}\n(exit {code})" if out else f"exit {code}"
                    # write-count note for the rewrite guard above — facts
                    # already counted this successful write via observe_output
                    if wm and code == 0:
                        ff = self.facts.files.get(path)
                        n = ff.writes if ff else 0
                        if n >= 2:
                            result += (f"\nNOTE: {path} has now been written "
                                       f"{n} times — the file exists, more "
                                       f"rewrites do not advance the quest. "
                                       f"RUN it (e.g. python3 -u {path}).")
                    result += await self._scan_flags(out, cmd, window)
                    # pane-busy escalation: consecutive execs that never
                    # finished (bounced off a held pane or still running)
                    # mean the pane is wedged — command variants won't fix
                    # it; a literal C-c or a type_in_pane answer will
                    if res.get("busy") or res.get("timed_out"):
                        key = window or "main"
                        n = self._busy_bounces.get(key, 0) + 1
                        self._busy_bounces[key] = n
                        if n >= 2:
                            result += (
                                f"\nPANE_WEDGED: the pane has been busy for "
                                f"{n} consecutive commands — "
                                f"stop trying command variants. Either "
                                f"interrupt with exec_in_kali 'C-c', or if a "
                                f"prompt waits for input (password/menu) "
                                f"answer it via type_in_pane NOW.")
                        else:
                            result += (
                                "\nNOTE: pane busy — interrupt with 'C-c', or "
                                "prefix possibly-hanging remote cmds "
                                "(ssh/nc/mysql to unverified hosts) with "
                                "'timeout 15'")
                    elif code is not None:
                        self._busy_bounces[window or "main"] = 0
                    if typed and code == 0 and out.strip():
                        # output-signature dedup: re-reads/re-greps of the same
                        # data return byte-identical output — the command-text
                        # dedup in ALREADY_DONE misses `cat f | grep` vs
                        # `grep x f` variants, so flag repeated OUTPUTS: the
                        # facts are settled, the model must move on
                        sig = hashlib.sha1(
                            "\n".join(l.strip() for l in out.splitlines()
                                      if l.strip())[:1500].encode()
                        ).hexdigest()[:12]
                        n = self._out_sigs.get(sig, 0) + 1
                        self._out_sigs[sig] = n
                        if n >= 2:
                            result += ("\nNOTE: this output is identical to a "
                                       "command you already ran — these facts "
                                       "are settled (see ALREADY_DONE). Take a "
                                       "DIFFERENT action toward the flag.")
                    if res.get("busy"):
                        text = (f"{where}**Could not run**\n"
                                f"```command\n$ {cmd}\n```\n"
                                f"{res.get('err') or 'pane busy'}")
                    elif res.get("status") == "denied" or res.get("error"):
                        why = res.get("error") or res.get("err") or "denied"
                        text = (f"{where}**Denied**\n"
                                f"```command\n$ {cmd}\n```\n"
                                f"{str(why)[:300]}")
                    else:
                        note = ("\n\n*(still running — watch the `pentrain-coach` tmux)*"
                                if res.get("timed_out") else "")
                        text = (f"{where}**Executed**\n"
                                f"```command\n$ {cmd}\n```")
                        if out.strip():
                            text += f"\n```output\n{out[-1500:]}\n```"
                        text += note
                    await self.client.send_chat(self.sid, text, kind="action_report",
                                                meta=self._msg_meta(window))
                    self._record_reply(text)
                    spoke = True
                    if grace_note:
                        result = grace_note + result
        elif t == "type_in_pane":
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            else:
                text_in = (a.get("text") or a.get("command")
                           or a.get("content") or "")
                try:
                    res = await self.client.type_in_pane(self.sid, text_in,
                                                         window=window)
                except (TimeoutError, httpx.HTTPError) as e:
                    return spoke, (
                        f"error: type transport failed "
                        f"({type(e).__name__}) — the input may still have "
                        f"reached the pane; probe before re-typing")
                out = res.get("out") or res.get("error") or res.get("err") or ""
                result = (percept.normalize(f"<type> {text_in}", out, None).reply
                          or "input sent")
                self.facts.observe_output(f"<type> {text_in}", out, None)
                result += await self._scan_flags(out, f"<type> {text_in}",
                                                 window)
                # keep the interactive fast-path alive while the pane is
                # still held (inside an ssh/ftp/vim session remote commands
                # must ALL go through type_in_pane — at LLM cadence, not
                # the ~90s tick). Missing field (old backend) → assume busy,
                # the bounded re-turn cap keeps that harmless. Workers track
                # their own pane via res.busy.
                if window is None:
                    self._pane_interactive = bool(res.get("busy", True))
                # a successful type means the wedge was answered, not bounced
                self._busy_bounces[window or "main"] = 0
                # interactive input is coach activity too — keep it visible in
                # command memory (marked so it can't pollute recon/write regexes)
                self.state.add_command(time.time(), f"<type> {text_in[:80]}",
                                       from_coach=True)
                rep = (f"{'[' + window + '] ' if window else ''}"
                       f"**Typed into the pane**\n"
                       f"```command\n$ {text_in[:90]}\n```")
                if out.strip():
                    rep += f"\n```output\n{out[-1200:]}\n```"
                await self.client.send_chat(self.sid, rep, kind="action_report",
                                            meta=self._msg_meta(window))
                self._record_reply(rep)
                spoke = True
        elif t == "submit_flag":
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            else:
                val = (a.get("value") or a.get("content") or "").strip()[:256]
                if not val:
                    return spoke, "error: empty flag value"
                # anti-hallucination: flag values are per-session — a value
                # that never appeared in ANY tool output is almost certainly
                # invented (seen live: model submitted `pentrAIn{f00th0ld…}`
                # while the real flag sat in the scrollback). Challenge once;
                # an identical resubmit goes through so a real-but-uncaptured
                # read stays possible — invented values just get corrected.
                ff = self.facts.flags.get(val)
                if (re.fullmatch(r"pentrAIn\{[^}\s]+\}", val)
                        and (ff is None or not ff.seen)
                        and not self._submit_challenged.get(val)):
                    self._submit_challenged[val] = 1
                    return spoke, (
                        f"denied: unverified `{val[:80]}` never appeared in any "
                        f"exec/type output this session — invented flags can "
                        f"never match (values are per-session) and wrong "
                        f"submits count. Re-read the file/output where the "
                        f"flag actually appeared and paste the EXACT string. "
                        f"(Submitting the same value again confirms it.)")
                await self.client.send_activity(self.sid, "submitting flag…",
                                                agent=window or "main")
                res = await self.client.submit_flag(self.sid, val)
                self.facts.flag_mark_submitted(val, bool(res.get("correct")))
                verdict = ("correct — flag solved" if res.get("correct")
                           else f"rejected ({res.get('error') or 'wrong value'})")
                result = f"submit {val[:80]} → {verdict}"
                text = f"Submitted flag `{val[:80]}` → **{verdict}**"
                if res.get("all_solved"):
                    result += "; all_solved"
                    text += " — all flags solved, quest complete"
                await self.client.send_chat(self.sid, text, kind="action_report",
                                            meta=self._draft_meta())
                self._record_reply(text)
                spoke = True
        elif t == "check_flag":
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            else:
                key = (a.get("flag_key") or "").strip()[:64]
                if not key:
                    return spoke, "error: empty flag_key"
                await self.client.send_activity(self.sid, f"verifying `{key}`…",
                                                agent=window or "main")
                res = await self.client.check_flag(self.sid, key)
                verdict = ("verified — flag solved" if res.get("correct")
                           else f"not satisfied ({res.get('error') or 'check failed'})")
                result = f"check {key} → {verdict}"
                text = f"Ran server check for `{key}` → **{verdict}**"
                if res.get("all_solved"):
                    result += "; all_solved"
                    text += " — all flags solved, quest complete"
                await self.client.send_chat(self.sid, text, kind="action_report",
                                            meta=self._draft_meta())
                self._record_reply(text)
                spoke = True
        elif t == "mark_checkpoint":
            cid = a.get("checkpoint_id")
            # only accept checkpoints the quest actually defines
            known = {c for c, _n, _p in self.matcher._rules}
            if not cid or cid not in known:
                result = "error: unknown checkpoint"
            elif cid in self.state.checkpoints_hit:
                result = "duplicate"
            else:
                self.state.checkpoints_hit.add(cid)
                await self.client.mark_checkpoint(self.sid, cid)
                result = "marked"
        elif t == "capture_screen":
            # rate-limit: one capture per 30s regardless of model enthusiasm
            if time.time() - self._last_capture_ts <= 30:
                result = "rate_limited"
            else:
                self._last_capture_ts = time.time()
                await self.client.send_activity(self.sid, "analyzing screen…",
                                                agent=window or "main")
                res = await self.client.capture_screen(self.sid)
                if res.get("png_b64"):
                    self.state.screen_desc = await self._describe_screen(res["png_b64"])
                    result = self.state.screen_desc[:400]
                else:
                    result = "no screenshot available"
        elif t == "spawn_agent":
            result = self._spawn_agent(a)
            if not result.startswith(("denied:", "error:")):
                wid = result.split(" — ")[0].split()[-1]
                rep = (f"Spawned worker on pane "
                       f"`{wid}` — "
                       f"{(a.get('task') or '')[:120]}")
                await self.client.send_chat(self.sid, rep,
                                            kind="action_report",
                                            meta={**self._draft_meta(),
                                                  "agent_ref": wid})
                spoke = True
        elif t == "collect_agent":
            result = await self._collect_agent(a)
        elif t == "agent_status":
            result = self._agent_status()
        elif t == "kill_agent":
            result = self._kill_agent(a)
        elif t == "wait":
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            else:
                try:
                    n = int(float(a.get("seconds") or a.get("content") or 30))
                except (TypeError, ValueError):
                    n = 30
                cap = int(self.cfg.get("coach", {}).get("wait_max_s", 180))
                n = max(1, min(n, cap))
                # don't sleep into a dying turn — the outer wait_for budget
                # would cancel mid-wait and the model never sees the result.
                # A worker waits against ITS OWN time cap, not the parent's
                # (both can run concurrently — the flag is parent-turn state)
                if window:
                    w = self._workers.get(window)
                    deadline = (w.started + float(
                        self.cfg.get("coach", {}).get(
                            "worker_time_cap_s", 300))) if w else None
                else:
                    deadline = self._turn_deadline
                left = (deadline - time.monotonic()) if deadline else None
                if left is not None and left < 20:
                    result = ("error: too little turn budget left for a wait "
                              "— act now or end the turn instead")
                else:
                    if left is not None:
                        n = min(n, int(left) - 10)
                    why = (a.get("why") or "").strip()[:120]
                    where = f"[{window}] " if window else ""
                    await self.client.send_activity(
                        self.sid,
                        f"{where}waiting {n}s" + (f" — {why}" if why else ""),
                        agent=window or "main")
                    rep = (f"{where}**Waiting {n}s**"
                           + (f" — {why}" if why else ""))
                    await self.client.send_chat(
                        self.sid, rep, kind="action_report",
                        meta=self._msg_meta(window))
                    self._record_reply(rep)
                    spoke = True
                    t_wait = time.monotonic()
                    aborted = False
                    # sliced like collect_agent — an operator message must
                    # preempt the pause instead of queueing behind it
                    while time.monotonic() - t_wait < n:
                        if self.state.pending_chat:
                            aborted = True
                            break
                        await asyncio.sleep(
                            min(2.0, n - (time.monotonic() - t_wait)))
                    actual = int(time.monotonic() - t_wait)
                    if aborted:
                        result = (f"wait aborted after {actual}s — operator "
                                  "message pending; handle the message first")
                    else:
                        result = (f"waited {actual}s — pane and facts "
                                  "unchanged; re-check the condition now")
                    key = window or "main"
                    streak = self._wait_streak.get(key, 0) + 1
                    self._wait_streak[key] = streak
                    if streak >= 3:
                        result += (f" NOTE: {streak} consecutive waits — if "
                                   "the condition still isn't met, reconsider "
                                   "the approach instead of waiting longer")
        elif t == "update_plan":
            # self-maintained roadmap — atomic full-replace so a truncated
            # rewrite can't leave zombie steps. A worker's plan lives on
            # its _Worker, never the parent's.
            items = normalize_plan(a.get("items") or a.get("plan") or [])
            target = (self._workers[window].plan
                      if window and window in self._workers
                      else self.state.plan)
            target.clear()
            target.extend(items)
            if not window:
                self.state.plan_updated = time.time()
            open_n = sum(1 for i in items if i["s"] != "done")
            result = (f"plan saved — {len(items)} steps "
                      f"({open_n} open): "
                      + " | ".join(f"[{'x' if i['s'] == 'done' else '>' if i['s'] == 'doing' else ' '}] {i['t']}"
                                  for i in items)[:600])
            asyncio.create_task(self.client.log_action(
                self.sid, "update_plan",
                {"items": items, "agent": window or "main"},
                {"open": open_n}))
            rep = (f"{'[' + window + '] ' if window else ''}"
                   f"**Plan:** {open_n} open / {len(items)} steps")
            # the structured items ride in meta — the feed renders a real
            # checklist card instead of markdown bullet soup
            meta = {**self._msg_meta(window), "plan": items,
                    "open": open_n}
            await self.client.send_chat(self.sid, rep, kind="plan_update",
                                        meta=meta)
            self._record_reply(rep)
            spoke = True
        # "none" or unknown → silence (reason captured above as working memory)
        if t == "none":
            result = "noted"
        if spoke:
            self.state.last_nudge_ts = time.time()
            self.state.nudges_sent += 1
        # an executed action (parent only — a worker's execs must not consume
        # the operator's directive) retires the pinned OPERATOR_DIRECTIVE so
        # it stops steering later turns; the chat message stays in history
        if (spoke and window is None and t in (
                "exec_in_kali", "type_in_pane", "submit_flag", "check_flag")):
            self.state.operator_directive = ""
        return spoke, result

    # ---------- parallel worker agents (L4 subagents) ----------

    def _spawn_agent(self, a: dict) -> str:
        """spawn_agent tool — launches a worker task on its own tmux window.
        Runs coach-internal; the backend only sees the worker's execs."""
        if self.state.autonomy_level < 4:
            return "denied: workers need autonomy level 4"
        if not self.state.subagents_enabled:
            return "denied: subagents are disabled (/subagents on or the UI chip)"
        task = (a.get("task") or a.get("content") or "").strip()
        if not task:
            return "error: empty task"
        max_w = int(self.cfg.get("coach", {}).get("max_workers", 3))
        if max_w < 1:
            return "denied: workers disabled (coach.max_workers < 1)"
        running = sum(1 for w in self._workers.values()
                      if w.status == "running")
        if running >= max_w:
            return (f"denied: all {max_w} worker slots busy — "
                    "collect_agent a finished one first")
        # slot = pane id — prefer a never-used window; reuse a finished
        # worker's slot only when all were spawned before (its report is
        # then overwritten — collect finished workers before respawning)
        running_ids = {w.id for w in self._workers.values()
                       if w.status == "running"}
        ids = [f"w{i}" for i in range(1, max_w + 1)]
        wid = next((i for i in ids if i not in self._workers),
                   next(i for i in ids if i not in running_ids))
        w = _Worker(id=wid, task=task[:500], started=time.monotonic())
        self._workers[wid] = w
        self._push_agents()
        w.task_obj = asyncio.create_task(self._worker_loop(w))
        # audit: the roster lifecycle is coach-internal — without a row the
        # backend (and any post-restart resync) never knew workers existed
        asyncio.create_task(self.client.log_action(
            self.sid, "spawn_agent", {"worker_id": wid, "task": task[:200]},
            {"spawned": wid}))
        return (f"spawned {wid} — \"{task[:120]}\". It works autonomously on "
                f"its own pane ({wid}); continue your own work and read its "
                f"report with collect_agent(\"{wid}\") when you need it.")

    async def _collect_agent(self, a: dict) -> str:
        """collect_agent tool — waits (bounded) for a worker's report."""
        wid = (a.get("worker_id") or a.get("id") or "").strip()
        w = self._workers.get(wid)
        if not w:
            return (f"error: unknown worker {wid!r} — known: "
                    f"{', '.join(sorted(self._workers)) or 'none'}")
        if w.status == "running":
            # wait in slices so operator chat can preempt — a blocking
            # collect must not hold the turn hostage for the full timeout
            wait_s = float(self.cfg.get("coach", {}).get("collect_wait_s", 40))
            deadline = time.monotonic() + wait_s
            while w.status == "running" and time.monotonic() < deadline:
                if self.state.pending_chat:
                    return (f"{wid} still running ({w.actions} actions) — "
                            "collect later")
                try:
                    await asyncio.wait_for(
                        asyncio.shield(w.task_obj),
                        min(2.0, deadline - time.monotonic()))
                except TimeoutError:
                    pass
                except asyncio.CancelledError:
                    raise
        # the wait may have raced a status transition — refresh the chips
        self._push_agents()
        status = w.status
        if status == "running":
            return (f"{wid} still running ({w.actions} actions, "
                    f"{int(time.monotonic() - w.started)}s) — task: "
                    f"\"{w.task[:80]}\"")
        # reports merge at finish time (_finish_worker) — collect reads the
        # text; if the worker is somehow still unmerged (killed race), do it
        merged = ""
        if w.report:
            note = self._merge_worker_report(w)
            merged = f"\n{note}" if note else "\n[facts already merged]"
        asyncio.create_task(self.client.log_action(
            self.sid, "collect_agent", {"worker_id": wid},
            {"status": status, "actions": w.actions}))
        return (f"{wid} {status} ({w.actions} actions):\n"
                f"{w.report or '(no report)'}{merged}")

    def _agent_status(self) -> str:
        if not self._workers:
            return "no workers spawned this session"
        now = time.monotonic()
        lines = []
        for wid in sorted(self._workers):
            w = self._workers[wid]
            lines.append(f"{w.id} {w.status} — {w.actions} actions, "
                         f"{int(now - w.started)}s — \"{w.task[:70]}\"")
            if w.plan:
                doing = next((i["t"] for i in w.plan if i["s"] == "doing"),
                             next((i["t"] for i in w.plan
                                   if i["s"] == "todo"), ""))
                open_n = sum(1 for i in w.plan if i["s"] != "done")
                lines.append(f"   plan: {open_n} open"
                             + (f" — next: {doing[:70]}" if doing else ""))
        return "workers:\n" + "\n".join(lines)

    def _kill_agent(self, a: dict) -> str:
        wid = (a.get("worker_id") or a.get("id") or "").strip()
        w = self._workers.get(wid)
        if not w:
            return f"error: unknown worker {wid!r}"
        if w.status != "running":
            return f"{wid} already {w.status}"
        if w.task_obj:
            w.task_obj.cancel()
        w.status = "killed"
        self._push_agents()
        asyncio.create_task(self.client.log_action(
            self.sid, "kill_agent", {"worker_id": wid}, {"killed": wid}))
        return f"{wid} killed — its pane ({wid}) keeps its scrollback"

    def _kill_all_workers(self) -> None:
        for w in self._workers.values():
            if w.status == "running":
                w.status = "killed"
                if w.task_obj:
                    w.task_obj.cancel()
        if self._workers:
            self._push_agents()

    def _merge_worker_report(self, w: _Worker) -> str:
        """Push a finished worker's report into shared facts — runs at
        finish time so findings exist even if the parent never collects
        (s46: both worker reports died uncollected). collect_agent then
        just READS the report instead of merging twice."""
        if w.merged or not w.report:
            return ""
        w.merged = True
        parsed = percept.parse_worker_report(w.report)
        if parsed:
            n = self.facts.apply_worker_report(w.id, parsed)
            bits = [f"{n['creds']} creds", f"{n['ports']} ports",
                    f"{n['findings']} findings"]
            return ("[merged into FACTS: " + ", ".join(bits) + "]")
        self.facts.apply_delta(
            percept.parse_output("", w.report), source=w.id)
        return "[prose report — extracted facts where possible]"

    async def _finish_worker(self, w: _Worker) -> None:
        """Terminal housekeeping for a worker: merge its report into shared
        facts, drop its live indicator, post the report into its own feed
        (meta.agent routes it there; leftover turn reasoning rides as
        meta.reasoning like the parent's), then refresh the roster chips."""
        self._merge_worker_report(w)
        await self.client.send_activity(self.sid, active=False, agent=w.id)
        if w.report:
            meta = self._msg_meta(w.id)
            await self.client.send_chat(
                self.sid, w.report[:2000], kind="action_report", meta=meta)
        self._push_agents()

    async def _worker_loop(self, w: _Worker) -> None:
        """One worker's act→observe→act loop — private message list (never
        touches _history: interleaved tool pairs would corrupt the parent's
        call/result pairing), shared guards/budgets via _dispatch(window)."""
        msgs = [{"role": "system",
                 "content": render_worker_prompt(
                     self.ctx, w, self.facts.render(500, compact=True),
                     plan_render(self.state.plan, cap=350,
                                 title="OPERATOR_PLAN"))},
                {"role": "user", "content": w.task}]
        cc = self.cfg.get("coach", {})
        turn_cap = int(cc.get("worker_turn_cap", 10))
        time_cap = int(cc.get("worker_time_cap_s", 300))
        t0 = time.monotonic()
        last_out = ""
        try:
            while (w.turns < turn_cap
                   and time.monotonic() - t0 < time_cap):
                resp = await self.llm.chat(msgs, tools=worker_tools())
                w.turns += 1
                # stash this turn's reasoning — the next message the worker
                # posts (exec report, final report) carries it as
                # meta.reasoning so its feed shows a thinking block like
                # the parent's persisted messages do
                self._worker_reasoning[w.id] = (
                    resp.get("reasoning") or "")[:3500]
                usage = (resp.get("raw") or {}).get("usage") or {}
                self.usage["tokens"] += int(usage.get("total_tokens", 0))
                asyncio.create_task(self.client.report_llm_usage(
                    self.sid, getattr(self.llm, "model", "?"), "worker",
                    resp.get("usage"), resp.get("latency_ms")))
                calls = resp.get("tool_calls") or []
                call_results: dict[str, str] = {}
                exec_acts = [a for a in resp["actions"]
                             if a.get("type") in WORKER_TOOL_NAMES
                             and a.get("type") != "none"]
                for a in resp["actions"]:
                    if a.get("type") == "none" and a.get("reason"):
                        note_txt = f"[{w.id}] {a['reason']}"[:300]
                        self.state.notes.append(note_txt)
                        self.state.notes = self.state.notes[-8:]
                        asyncio.create_task(self.client.log_action(
                            self.sid, "note",
                            {"text": note_txt, "agent": w.id}, {}))
                    did, res = await self._dispatch(a, proactive=True,
                                                  window=w.id)
                    if did:
                        w.actions += 1
                    if cid := a.get("_call_id"):
                        call_results[cid] = res
                    last_out = res or last_out
                # per-turn roster push — the chip's action count stays live
                # instead of freezing at its spawn-time snapshot
                self._push_agents()
                if not calls or not exec_acts:
                    # no tool calls or only 'none' — the worker is done; its
                    # trailing message IS the report to the parent
                    w.report = ((resp.get("content") or "").strip()
                                or last_out[-1500:] or "(finished silently)")
                    w.status = "done"
                    # a failed report-post must not flip a finished worker
                    # to 'failed' and overwrite its real report
                    with contextlib.suppress(Exception):
                        await self._finish_worker(w)
                    return
                # assistant/tool pairing identical to the parent turn — strict
                # endpoints reject a tool_call left without its reply
                msgs.append({"role": "assistant",
                             "content": (resp.get("content") or None),
                             "tool_calls": calls})
                for i, call in enumerate(calls):
                    cid = call.get("id") or f"call_{i}"
                    msgs.append({"role": "tool", "tool_call_id": cid,
                                 "content": call_results.get(
                                     cid, "error: dropped")[:2000]})
                msgs = msgs[:1] + msgs[-29:]  # bounded ctx, keep the system prompt
            w.status = "timeout"
            w.report = (f"hit worker caps after {w.actions} actions/"
                        f"{w.turns} turns — {last_out[-800:]}")
            with contextlib.suppress(Exception):
                await self._finish_worker(w)
        except asyncio.CancelledError:
            w.status = "killed"
            with contextlib.suppress(Exception):
                await self._finish_worker(w)
            raise
        except Exception as e:
            w.status = "failed"
            w.report = f"worker crashed: {e}"
            await log.awarning("worker failed", session=self.sid,
                               worker=w.id, error=str(e))
            with contextlib.suppress(Exception):
                await self._finish_worker(w)

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
            asyncio.create_task(self.client.report_llm_usage(
                self.sid, self._vision_model, "vision",
                resp.get("usage"), resp.get("latency_ms")))
            return (resp.get("content") or "")[:600]
        except LlmError as e:
            return f"vision capture failed: {e}"
