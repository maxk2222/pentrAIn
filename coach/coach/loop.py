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
import json
import re
import shlex
import time
from dataclasses import dataclass, field

import httpx
import structlog

from . import guides, percept, playbooks, ptg, research
from . import traj as _traj
from .client import BackendClient
from .config import get_config
from .facts import _USER_AT_HOST, FLAG_RE, WRITE_RE, FactsDB

# settled-denial forms rendered by percept: denied:{svc}-{user}@{host},
# denied:{svc}-auth@{host}, denied:sudo|docker@{host}, unreachable:{ip}@{v}
_DENIAL_FORM = re.compile(r"denied:(\w+)(?:-([\w.\-]+))?@(\S+)")


def _shell_segments(cmd: str) -> list[str]:
    """Split at shell separators only at quote-depth 0. A `;` inside the
    remote tail (`ssh u@h 'python3 -c "a;b"'`) is code ON the pivot —
    splitting there fabricates local segments out of remote strings and
    pinned a web01-vantage urllib call to `filtered:.32@kali` (s84)."""
    segs, cur = [], []
    sq = dq = esc = False
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if esc:
            cur.append(ch); esc = False; i += 1; continue
        if ch == "\\":
            cur.append(ch); esc = True; i += 1; continue
        if sq:
            cur.append(ch)
            if ch == "'":
                sq = False
            i += 1; continue
        if dq:
            cur.append(ch)
            if ch == '"':
                dq = False
            i += 1; continue
        if ch == "'":
            sq = True; cur.append(ch); i += 1; continue
        if ch == '"':
            dq = True; cur.append(ch); i += 1; continue
        if cmd.startswith(("&&", "||"), i):
            segs.append("".join(cur)); cur = []; i += 2; continue
        if ch in "|;\n":
            segs.append("".join(cur)); cur = []; i += 1; continue
        cur.append(ch); i += 1
    segs.append("".join(cur))
    return segs
from . import facts as facts_mod
from .llm import LlmClient, LlmError
from .policy import Policy
from .prompts import (
    _PLAN_STALE_S,
    build_context_msg,
    chat_prompt,
    plan_render,
    render_worker_prompt,
    system_prompt,
)
from .research import ResearchClient
from .state import CheckpointMatcher, SessionState, normalize_plan
from .tools import WORKER_ROLES, WORKER_TOOL_NAMES, tools_for_level, trim_history, wire_history, worker_tools
from .websearch import WebSearch

log = structlog.get_logger(__name__)

HISTORY_CAP = 14           # user/assistant messages kept in-context
CHAT_DEBOUNCE_S = 1.5      # coalesce rapid trainee messages into one turn
LLM_TURN_BUDGET_S = 600    # hard bound for one LLM turn incl. action dispatch;
                           # local models are slow — a full takeover chain
                           # must fit inside this
                         # a wedged call gets cancelled, releasing the lock
# tool types that keep an in-turn chain alive — they have server-side effects
# whose results the model should see immediately (send_chat/offer_hint/none
# end the chain: the model only wanted to talk or pause)
# backend/qga-side exec failures — the command never reached the pane. Not
# command output, so matching on res["error"] only (never on `out`).
_INFRA_ERR = (r"qemu guest agent|qga command|agent/exec|agent is not running|"
              r"is not running|guest-exec|transport failed|500:|502:|503:")


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
    # specialist contract — narrows the worker's operating scope (recon/
    # web/creds/svc/privesc/pivot/verify) and what its report must carry
    role: str = "general"
    done_when: str = ""         # acceptance criterion from spawn_agent
    task_id: str = ""           # PTG binding — finish marks the task
    wrap_nudged: bool = False   # budget-low wrap-up already injected
    last_out: str = ""          # newest tool result — on kill, its tail
    # becomes the report so partial findings merge instead of dying
    task_obj: asyncio.Task | None = None


def _iso_to_epoch(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        import datetime as dt
        return dt.datetime.fromisoformat(iso).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _safe_int(v: object, default: int) -> int:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _render_searchsploit(out: str, code: int | None, q: str) -> str:
    """searchsploit --json → compact rows. Honest degradation: a non-json
    tail (apt hint, crash) still surfaces as the reply instead of vanishing."""
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, TypeError):
        tail = out.strip()[-700:]
        return (f"searchsploit exit={code} — output was not json "
                f"(local index damaged?)\n{tail or '(no output)'}")
    rows = data.get("RESULTS_EXPLOIT") or []
    shell = data.get("RESULTS_SHELLCODE") or []
    if not rows and not shell:
        return (f"no exploit-db hits for '{q}' — rephrase (drop version, "
                "vendor+product only) or search the web if online")
    lines = []
    for r in rows[:15]:
        edb = r.get("EDB-ID") or "?"
        verified = "*" if str(r.get("Verified")) == "1" else ""
        lines.append(
            f"EDB-{edb}{verified} | {str(r.get('Title') or '')[:90]} | "
            f"{r.get('Type') or '?'}/{r.get('Platform') or '?'} | "
            f"{r.get('Path') or ''}")
    more = len(rows) - len(lines)
    head = (f"{len(rows)} exploit(s){' +' + str(len(shell)) + ' shellcode' if shell else ''}"
            f" for '{q}' (* = verified):\n")
    return (head + "\n".join(lines)
            + (f"\n…+{more} more — narrow with title_only or more terms"
               if more > 0 else "")
            + "\nread one: exec_in_kali cat <path> (or searchsploit -m "
              "<id> to copy it into cwd)")


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
        # eval ablations — coach.ablation = "ptg,roles,coverage,memory"
        # disables subsystems for ablation runs (P3 eval). One flag set,
        # checked at each feature's seam; empty in production.
        _abl = str(cfg.get("coach", {}).get("ablation") or "")
        self._ablate = {x.strip().lower()
                        for x in _abl.replace(";", ",").split(",")
                        if x.strip()}
        self.state.ablation = self._ablate
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
        # infra-error backoff: backend/qga 500s are NOT command results — the
        # model otherwise retypes payloads into a dead exec channel (s49:
        # 9 wasted turns across a ~12min qga outage). Consecutive errors
        # beyond a threshold bounce until a probe succeeds.
        self._infra_errors = 0
        self._infra_last_probe = 0.0
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
        # last in-result plan reminder — the context-block "stale" suffix is
        # advisory and got ignored for 40+ actions (s65); the tool RESULT is
        # the channel the model always reads
        self._plan_stale_ping = 0.0
        self._allowed_nets: list[ipaddress.IPv4Network] = []  # target /24s
        # engagement scope (ctx["scope"]) — populated in start(); locked
        # means every IP/host literal must sit inside the whitelist
        self._scope_locked = False
        # free-lab mode (topology.free on the quest) — open Kali, no ROE:
        # foreign-ip/host guards short-circuit; flag/checkpoint tools are
        # not offered. VM-kill deny patterns stay backend-side regardless.
        self._free = False
        self._scope_required = False   # locked but EMPTY — deny everything
        self._scope_hosts: set[str] = set()
        self._scope_ports: set[int] = set()
        self._workers: dict[str, _Worker] = {}   # spawned subagents w1..wN
        # per-worker in-turn reasoning — attached once to that worker's next
        # posted message (pop-once), mirroring the parent's _turn_reasoning
        self._worker_reasoning: dict[str, str] = {}
        # denials already surfaced in a guaranteed-read NOTE — PER WINDOW:
        # a worker's frozen facts snapshot makes the note its only channel,
        # and a shared set lets one agent eat the note for everyone
        self._denial_seen: dict[str, set[str]] = {}
        self._guides_hinted: set[str] = set()  # modules already hinted on
        # the guaranteed-read channel — one push per module per session
        # guide pull dedup: window → module ids already fetched — a repeat
        # pull of the same recipe must not re-pay its body tokens (s1: the
        # .git module was fetched 5x inside 18min by the same window)
        self._guide_fetched: dict[str, set[str]] = {}
        # worker-dup advisory dedup: (worker_id, cmd-target) already noted
        # — the hint is pop-once per pair, not a per-scan nag
        self._dup_noted: set[tuple[str, str]] = set()
        # persistent interactive channels (channel_open) — named tmux
        # windows c-<name> for ssh/msfconsole/nc-style sessions the model
        # converses with turn by turn. Max 2; a channel survives across
        # turns until channel_close (a coach restart orphans the window —
        # reopening the name reuses the pane).
        self._channels: dict[str, dict] = {}
        # worker completion notices → the parent's guaranteed-read channel.
        # Without this the parent only learns of a finished worker by
        # polling agent_status (s1: 3 workers died unnoticed, never
        # collected — their findings arrived only via silent fact-merge)
        self._worker_done: list[str] = []
        # denial-repeat escalation: tool|cmd-sig → times denied — the same
        # "denied:" text reads as fresh each turn, so a stubborn model
        # retries forever (s1: deploy@10.1.10.32 denied 3× identically)
        self._deny_counts: dict[str, int] = {}
        # evidence re-read guard: read-verb command on the same path N times
        # returns data already in history — soft advisory at n>=3 per window
        self._read_counts: dict[str, int] = {}
        # key-free research — one shared client so the DDG debounce covers
        # parent + all workers (they'd otherwise stampede the endpoint)
        self._web = WebSearch()
        self._research = ResearchClient()
        # deep-effort spend marker: last_progress_ts at which the one deep
        # turn of this no-progress window already ran — at L4, stuck>hint_s
        # makes stage-2 the default state, so every-turn-deep burned the
        # 600s budget in cancels (s84: 3/30min, s1 too). Progress re-earns
        # depth; a spent or cancelled deep falls back to routine effort.
        self._deep_spent_ts: float = 0.0
        # observer field-note tracking: window → note ids already pushed;
        # note id → (progress_ts, exec_count) at push for hit feedback
        self._notes_hinted: dict[str, set[int]] = {}
        self._notes_pushed: dict[int, tuple[float, int]] = {}
        # cred-spray advisory: (secret, host) pairs already noted — the hint
        # is pop-once per target so password-reuse tries stay legitimate
        self._spray_noted: set[tuple[str, str]] = set()
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
        if s.get("state") in ("solved", "aborted", "failed",
                              "resetting", "aborting"):
            # "resetting" is not terminal but equally poisonous: the drop
            # fires on the state event, yet telemetry/terminal events keep
            # arriving and _ensure_coach would re-attach a coach that then
            # execs against a rolling-back VM (s84: actions kept logging
            # through the whole snapshot rollback)
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
        # engagement scope object (sessions.scope_json via coach_bridge —
        # ctx["scope"]): locked=True means a HARD whitelist — every IP
        # literal in a command (public ones included) must sit inside the
        # authorized nets, and nothing learned from tool output widens it.
        # Unlocked (default): the historical range behavior — target /24s +
        # pivot-safe ips_seen relaxation.
        self._free = bool(
            self.ctx.get("session", {}).get("free_mode"))
        scope_obj = self.ctx.get("scope") or {}
        self._scope_locked = bool(scope_obj.get("locked"))
        # 'required' = engagement pack with no whitelist declared yet —
        # EVERY target denies until the operator POSTs the scope
        self._scope_required = bool(scope_obj.get("required"))
        self._scope_hosts = {str(h).lower().strip(".")
                             for h in (scope_obj.get("hosts") or [])}
        self._scope_ports = {int(p) for p in (scope_obj.get("ports") or [])
                             if str(p).isdigit()}
        # known-good target space for the hallucinated-IP guard: each target's
        # /24 (or explicit CIDR — home-lab carries "lan-scope=192.168.3.131/24"),
        # plus every IP ever seen in tool output (pivot-safe — a host the model
        # discovers in output becomes reachable, one it invents does not).
        # In scope-locked mode targets are NOT auto-seeded — the operator's
        # whitelist is the only authority (a pack listing an out-of-scope
        # target must fail, not widen authorization).
        for t in (self.ctx.get("quest", {}).get("targets") or []):
            ip = (t.get("ip") or "").strip()
            if not ip:
                continue
            try:
                net = (ipaddress.ip_network(ip, strict=False) if "/" in ip
                       else ipaddress.ip_network(f"{ip}/24", strict=False))
                if not self._scope_locked and net not in self._allowed_nets:
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
        if scope and not self._scope_locked:
            try:
                net = ipaddress.ip_network(scope, strict=False)
                if net not in self._allowed_nets:
                    self._allowed_nets.append(net)
                self.facts.ips_seen.add(scope.split("/")[0])
            except ValueError:
                pass
        if self._scope_locked:
            for c in (scope_obj.get("nets") or []):
                try:
                    net = ipaddress.ip_network(str(c), strict=False)
                except ValueError:
                    continue
                if net not in self._allowed_nets:
                    self._allowed_nets.append(net)
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
        if not self.state.plan and self.state.autonomy_level >= 4:
            # deterministic scaffold: s61/s65/s66 each ran 40-70 actions
            # with zero update_plan calls — seed the checklist from the
            # flag list so it renders, auto-marks on solves, and remains
            # the model's to rewrite (rendered as "yours — update via
            # update_plan")
            open_flags = [str(f.get("key")) for f in self.ctx.get("flags", [])
                          if f.get("key") and not f.get("solved")]
            if open_flags:
                self.state.plan = normalize_plan(
                    [{"t": "Recon: enumerate hosts/services & entry points",
                      "s": "doing"}]
                    + [{"t": f"Solve flag {k}", "s": "todo"}
                       for k in open_flags]
                    + [{"t": "Verify: all flags submitted, wrap up",
                        "s": "todo"}])
                self._plan_push_card("seeded")
        # a restart doesn't make the plan stale — the staleness nudge only
        # fires when the MODEL hasn't refreshed in-session for a while
        self.state.plan_updated = time.time()
        # reconcile the restored plan against flags already solved — solves
        # under a dead coach never got their auto-marks (s84: card showed
        # 'Solve flag-1' todo + recon 'doing' although flag-1 was submitted)
        if self.state.plan:
            # only retire flag-named steps: a solve from a previous attempt
            # says nothing about THIS run's recon (range may have reset)
            marked = sum(
                self._plan_mark_solved(str(f.get("key") or ""))
                for f in self.ctx.get("flags", []) if f.get("solved"))
            if marked:
                self._plan_push_card("reconciled")
        self.state.notes = [str(n)[:300]
                            for n in self.ctx.get("coach_notes") or []][-8:]
        # agent-authored lessons — recorded mid-run via record_lesson,
        # replayed here so a restart doesn't lose the model's own distilled
        # session knowledge (it's what FACTS.lessons renders from)
        for lt in self.ctx.get("lessons") or []:
            if isinstance(lt, dict):
                self.facts.add_lesson(str(lt.get("text") or ""),
                                      str(lt.get("agent") or "main"))
            else:
                self.facts.add_lesson(str(lt))
        # observer field notes — memory only: reachable via lookup_guide and
        # tag-matched push-hints, deliberately NOT rendered into the prompt
        self.facts.set_field_notes(self.ctx.get("field_notes"))
        # coverage ledger + shared notes — agent-owned bookkeeping logged
        # via coach_actions (like update_plan); replay the writer log so a
        # restart keeps 'what was covered'. Worker-contributed rows ride
        # the worker_reports merge above — no separate log for them.
        for row in self.ctx.get("ledger_log") or []:
            if not isinstance(row, dict):
                continue
            args = row.get("args")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (TypeError, ValueError):
                    args = {}
            if isinstance(args, dict):
                tool = str(row.get("tool") or "")
                self.state.coverage.apply(tool, args)
                self.state.pad.apply(tool, args)
                if tool == "record_finding":
                    self.facts.apply_finding(
                        args, owner=str(args.get("agent") or "main"))
                elif tool == "threat_model":
                    self.state.threat_model = {
                        k: str(v)[:200] for k, v in args.items()
                        if k in ("attacker", "boundaries", "assets") and v}
        # orphaned workers: spawned pre-restart, killed with the process —
        # their command outputs reseeded via coach_outputs but the TASK died.
        # A note is all the parent needs to not re-do (or misplace) their work
        for wo in self.ctx.get("worker_orphans") or []:
            note = (f"{wo.get('agent', 'w?')} died with a coach restart — "
                    f"task was: \"{str(wo.get('task') or '')[:140]}\" — its "
                    "command outputs already live in FACTS")
            if note not in self.state.notes:
                self.state.notes.append(note)
        self.state.notes = self.state.notes[-8:]
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
        # deep-effort spend marker survives the restart via the traj file —
        # without this every redeploy burns one fresh 600s deep cancel.
        # last_progress_ts re-seeds to attach-time when no real progress
        # events exist, so the marker must clamp forward: the pre-restart
        # no-progress window CONTINUES, only new observed progress re-earns
        _restored_deep = _traj.last_deep_ts(self.sid)
        self._deep_spent_ts = (max(_restored_deep, time.time())
                               if _restored_deep else 0.0)
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
        if self._research:
            await self._research.aclose()
        if self._web:
            await self._web.aclose()

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
        # a session parked in 'ready' then activated must not look
        # stuck-since-attach — started_at/ready_at are liveness signals
        # too, but only ever move the clock FORWARD so real progress
        # (a newer last_progress_ts) is never rewound by an older seed
        seed = max((x for x in (_iso_to_epoch(s.get("started_at")),
                                _iso_to_epoch(s.get("ready_at"))) if x),
                   default=0.0)
        self.state.last_progress_ts = max(self.state.last_progress_ts, seed)
        if self.state.last_activity_ts <= 0:
            self.state.last_activity_ts = self.state.last_progress_ts
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
            elif etype == "observer_hint":
                # queued, pop-once — lands on the next tool result where the
                # model is guaranteed to read it; not a user message
                text = str(data.get("text") or "")[:400]
                if text:
                    self.state.pending_observer_hints.append(text)
                    del self.state.pending_observer_hints[:-4]
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
        budget = int(self.cfg.get("coach", {}).get("action_budget", 400))
        cc = self.cfg.get("coach", {})
        # adaptive effort with decay: deep reasoning is spent ONCE per
        # no-progress window — at L4, stuck>hint_s makes stage-2 the
        # default state, so every-turn-deep burned the 600s turn budget
        # in cancels (s84: 3/30min; s1: medium still cancelled). New
        # progress re-earns depth; a cancelled deep turn leaves it spent
        # (the marker was set pre-turn) — immediate routine backoff.
        routine_eff = cc.get("effort_routine") or "low"
        if (decision.stage >= 2
                and self.state.last_progress_ts > self._deep_spent_ts):
            effort = (cc.get("effort_deep")
                      or self.cfg.get("llm", {}).get("reasoning_effort")
                      or "high")
            # wall-clock, not last_progress_ts: the traj file survives
            # restarts, so a post-restart attach can restore the marker —
            # otherwise every redeploy buys one wasted 600s deep cancel
            self._deep_spent_ts = time.time()
            self._traj.record(kind="effort", deep=True)
        else:
            effort = routine_eff
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
                    proactive=True, effort=effort),
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
                        proactive=True, effort=effort),
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
                           record_user=user_msg,
                           effort=self.cfg.get("coach", {}).get(
                               "effort_chat") or "low"),
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
                        proactive: bool = False, record_user: str | None = None,
                        effort: str | None = None) -> bool:
        """Draft-safety wrapper — EVERY exit path of a turn (normal return,
        dispatch exception, cancel at the turn budget) must close the UI's
        streaming draft, or an open 'thinking' bubble ghosts forever."""
        self._turn_deadline = time.monotonic() + LLM_TURN_BUDGET_S
        try:
            return await self._llm_turn_body(
                user_msg, force_reply=force_reply, proactive=proactive,
                record_user=record_user, effort=effort)
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
                             record_user: str | None = None,
                             effort: str | None = None) -> bool:
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
                "takeover_chain_max", 48))
            chain_len = 0
            while True:
                pushed = False
                last_push = 0.0   # each sub-response streams its own draft
                # rebuilt per sub-call: an autonomy/subagents switch mid-chain
                # (drained between calls) narrows/widens the toolset at once
                tools = (tools_for_level(
                    self.state.autonomy_level,
                    subagents=self.state.subagents_enabled,
                    free=self._free)
                    if tools_active else None)
                if tools and self._ablate:
                    # eval ablation — hide the ablated subsystem's tools
                    # from the offered set; the model can't call what it
                    # never sees (dispatch stays a second gate)
                    drop = set()
                    if "coverage" in self._ablate:
                        drop |= {"record_coverage", "update_coverage",
                                 "list_coverage", "create_note",
                                 "list_notes"}
                    if "memory" in self._ablate:
                        drop |= {"search_memory", "record_play",
                                 "play_outcome"}
                    if drop:
                        tools = [t for t in tools
                                 if t["function"]["name"] not in drop]
                try:
                    resp = await self.llm.chat(messages, on_delta=on_delta,
                                               tools=tools,
                                               reasoning_effort=effort)
                except (LlmError, httpx.HTTPError) as e:
                    # one quiet retry — a slow/flaky endpoint shouldn't kill
                    # the turn outright; the turn budget keeps worst-case
                    # bounded
                    await log.awarning("llm call failed, retrying once",
                                       error=str(e))
                    try:
                        resp = await self.llm.chat(messages, tools=tools,
                                                   reasoning_effort=effort)
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
        # authorize the whole net — the multi-segment pivot case.
        # scope_locked: NOTHING learned from output widens authorization —
        # a discovered CIDR is evidence, not permission.
        for cidr in (self._CIDR_RE.findall(out or "")
                     if not self._scope_locked else ()):
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
    _READ_VERB = re.compile(
        r"\b(?:cat|grep|egrep|fgrep|tail|head|ls|strings|wc|file|stat)\b")
    _WRITE_HINT = re.compile(
        r">(?!\s*/dev/null|&\d)|\s-o[NAXSG]?\s|\btee\b|"
        r"\b(?:nmap|nikto|curl|wget|ssh|scp|msfconsole|hydra|hashcat|john|"
        r"sqlmap|gobuster|ffuf|dirsearch|nc|ncat|aircrack-ng|masscan)\b")
    _PATHISH = re.compile(r"(?:~|/)[\w./*-]{3,}")

    def _foreign_ip(self, cmd: str) -> str | None:
        """Private/link-local literal that's neither inside a target /24 nor
        seen in earlier output. Public IPs pass (internet uplink); observed
        IPs pass (pivot/discovered hosts); invented ones are denied — they
        hang every connect (session 31: model merged kali's 10.1.10.5 into
        10.42.0.5 and burned ~10 turns on it).

        scope_locked flips this to a HARD whitelist: every IP literal —
        public included — must sit inside the authorized nets. ips_seen no
        longer relaxes anything: output is evidence, not permission.
        Loopback/link-local/multicast/reserved literals stay free (127.x
        localhosts, 169.254.x noise, netmask-looking 255.x tokens)."""
        # unlocked: no baseline — can't judge foreign. LOCKED with an empty
        # whitelist denies everything (a 'required' scope object means the
        # operator hasn't declared targets yet)
        if self._free:
            return None        # free lab — no ROE, every literal reachable
        if not self._allowed_nets and not self._scope_locked:
            return None
        for lit in self._IP_RE.findall(cmd):
            try:
                ip = ipaddress.ip_address(lit)
            except ValueError:
                continue
            if (ip.is_loopback or ip.is_link_local or ip.is_multicast
                    or ip.is_reserved or ip.is_unspecified):
                continue
            if self._scope_locked:
                if any(ip in n for n in self._allowed_nets):
                    continue
                return lit
            if not ip.is_private:
                continue
            if lit in self.facts.ips_seen:
                continue
            if any(ip in n for n in self._allowed_nets):
                continue
            return lit
        return None

    _URL_RE = re.compile(r"(?:https?|ftp)://[^\s'\"<>]+", re.IGNORECASE)
    _USER_AT = re.compile(r"\b[\w.-]+@((?:[a-z0-9-]+\.)+[a-z]{2,})\b",
                          re.IGNORECASE)
    # bare-domain check restricted to classic gTLDs — script extensions
    # (.py/.sh/.pl/.md/.io/.dev/...) must never read as hosts
    _BARE_DOM = re.compile(
        r"\b((?:[a-z0-9-]+\.)+(?:com|net|org|edu|gov|int|mil|biz|info))\b",
        re.IGNORECASE)

    def _host_allowed(self, host: str) -> bool:
        """Hostname vs scope whitelist — exact or subdomain of a scope host."""
        h = host.lower().strip(".")
        return any(h == s or h.endswith("." + s) for s in self._scope_hosts)

    def _foreign_host(self, cmd: str) -> str | None:
        """scope_locked only: URL authorities, user@domain targets and bare
        classic-gTLD tokens must be authorized — hostnames are checked
        against scope.hosts (subdomains included), IP authorities against
        the nets, and a URL's explicit port against scope.ports when set."""
        if self._free:
            return None        # free lab — hostnames are never foreign
        def _check(host: str, port: int | None) -> str | None:
            host = host.strip()
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                ip = None
            if ip is not None:
                if (ip.is_loopback or ip.is_link_local or ip.is_multicast
                        or ip.is_reserved):
                    return None
                if not any(ip in n for n in self._allowed_nets):
                    return host
            elif not self._host_allowed(host):
                return host
            # authorized target — an explicit URL port still honors the
            # ROE port whitelist when the operator declared one
            if (port is not None and self._scope_ports
                    and port not in self._scope_ports):
                return f"{host}:{port}"
            return None

        for m in self._URL_RE.finditer(cmd):
            auth = m.group(0).split("://", 1)[1].split("/", 1)[0]
            auth = auth.rsplit("@", 1)[-1]           # strip userinfo
            if auth.startswith("["):                  # [v6]:port
                host, _, ps = auth[1:].partition("]")
                ps = ps.lstrip(":")
            else:
                host, _, ps = auth.partition(":")
            try:
                port = int(ps) if ps else None
            except ValueError:
                port = None
            bad = _check(host, port)
            if bad:
                return bad
        for rex in (self._USER_AT, self._BARE_DOM):
            for host in rex.findall(cmd):
                bad = _check(host, None)
                if bad:
                    return bad
        return None

    def _denial_match(self, cmd: str) -> str | None:
        """Exec cmd vs. settled denial facts — the FIRST matching dead end
        or None. Conservative: only fires on same evidence, never fuzzy.
          unreachable:{ip}@{vantage} — ip named in the REMOTE part of a
            pivot to {vantage} (or anywhere when vantage is kali)
          filtered:{ip}@{vantage}    — same scoping, but only scan-family
            commands (ping/ssh stay free)
          missing:{tool}@{vantage}   — tool named in the remote part
          denied:{svc}-{user}@{h}    — same binary + user in the LOCAL
            invocation incl. the user@host token itself
          denied:sudo|docker@{h}     — capability dead ON the host: the
            tool named in the remote part only
        ({svc}-auth denials are NOT matched: they don't record which cred
        failed, and the working pivot uses the same svc+host pair — an
        ssh-auth@shop01 entry would brick every valid sshpass pivot.)
        Scoping: `sshpass -p x ssh u@web01 'expect ...'` runs sshpass on
        KALI and expect ON web01 — a fact about web01 must only see the
        remote tail, or every correctly-scoped pivot gets bricked."""
        if not self.facts.denials:
            return None
        cmd = cmd or ""
        # shell separators restart the local context — `ssh u@a 'x' | ssh
        # u@b 'y'` runs 'x' on a but a NEW local command for b. A single
        # head/tail split would pin b's tools onto a (s84: `ssh u@web01
        # 'cat f' | sshpass ssh u@app01 'mkdir'` got denied by
        # missing:sshpass@web01 though that sshpass ran on kali — and the
        # actually-dead direct connect to app01 went unseen by
        # filtered:app01@kali).
        segs = _shell_segments(cmd)

        def _head(seg: str) -> str:
            """Segment text up to the first user@host token = local part."""
            m = _USER_AT_HOST.search(seg)
            return seg[:m.end()] if m else seg

        # kali facts are judged PER SEGMENT — joining heads let an IP from
        # a remote python-string pair with a sibling segment's ssh
        # (s84: `ssh u@web01 'python3 urllib http://.32/'` was denied by
        # filtered:.32@kali though the connect ran on web01)

        def _tail(host: str) -> str:
            """The remote portion — what executes ON `host` ('' when the
            host isn't invoked). For vantage 'kali' there is no remote."""
            if host == "kali":
                return ""
            out = []
            for s in segs:
                m = re.search(rf"\S+@{re.escape(host)}\b", s)
                if m:
                    out.append(s[m.end():])
            return " ".join(out)

        _MISSING_CALL = lambda k, s: re.search(
            rf"(?:^|[\s;|&'\"`(]){re.escape(k)}\b", s)
        _CONNECT = re.compile(
            r"\b(nmap|masscan|rustscan|unicornscan|nc|netcat|fping|ping|"
            r"ssh|sshpass|curl|wget|telnet|sshuttle|proxychains4?|socat)\b")
        # availability probes are not invocations — `which expect python3
        # perl` must pass a known-missing:expect fact or the whole probe
        # (and the info about the OTHER tools) dies with it (s84 live)
        _PROBE = re.compile(
            r"(?:^|[\s;|&'\"`(])(?:which|whereis|locate|type|hash)"
            r"(?:\s+[\w./+-]+)+"
            r"|(?:^|[\s;|&'\"`(])command\s+-[vV](?:\s+[\w./+-]+)+")

        def _deny(key: str, dn: str, scope: str) -> bool:
            """key mentioned in scope + the denial's activation evidence."""
            if not re.search(rf"\b{re.escape(key)}\b", scope):
                return False
            if dn.startswith("unreachable:"):
                return True
            if dn.startswith("missing:"):
                # the tool can never appear — no internet means nothing to
                # install it with. Only when actually INVOKED though:
                # preceded by a command boundary, not '/' — `scp
                # /usr/bin/sshpass u@h:/tmp/` ships the tool as PAYLOAD to
                # fix exactly this denial and must pass (s84 live). And
                # `which <tool>` is a PROBE, not a call — strip probe
                # invocations before the invocation check.
                return bool(_MISSING_CALL(key, _PROBE.sub(" ", scope)))
            # filtered = every scanned port dead — scans AND connect
            # attempts to the ip are dead ends. A bare user@ip token
            # counts as a connect too (-J hops).
            return bool(_CONNECT.search(scope)
                        or re.search(rf"\S+@{re.escape(key)}\b", scope))

        for dn in self.facts.denials:
            if dn.startswith(("unreachable:", "filtered:", "missing:")):
                rest = dn.split(":", 1)[1]
                key, _, vantage = rest.rpartition("@")
                if not key:
                    continue
                if vantage == "kali":
                    # each local segment independently — cross-segment
                    # joins must not fabricate evidence
                    if any(_deny(key, dn, _head(s)) for s in segs):
                        return dn
                else:
                    # host facts see only what runs ON that host
                    if _deny(key, dn, _tail(vantage)):
                        return dn
                continue
            m = _DENIAL_FORM.match(dn)
            if not m:
                continue
            svc, user, host = m.group(1), m.group(2), m.group(3)
            if user == "auth":
                continue
            tail = _tail(host)
            if user and svc == "ssh":
                # the denied thing IS the connection to host — ssh+user in
                # the local invocation of the segment invoking that host
                for s in segs:
                    mh = re.search(rf"\S+@{re.escape(host)}\b", s)
                    if not mh:
                        continue
                    head = s[:mh.end()]
                    if (re.search(r"\bssh\b", head)
                            and re.search(rf"\b{re.escape(user)}\b", head)):
                        return dn
                continue
            # client-tool or capability denial — the command ran ON the
            # host, so only the remote tail counts (`sudo sshpass ssh
            # u@h 'id'` runs sudo on Kali and must stay free)
            if (tail
                    and re.search(rf"\b{re.escape(svc)}\b", tail)
                    and (user is None
                         or re.search(rf"\b{re.escape(user)}\b", tail))):
                return dn
        return None

    _HOST_LIKE = re.compile(
        r"\b(?:web|app|db|dc|ws|srv|mail|file|proxy|vpn|dev|test|stage)\d+\b")

    def _worker_target_dup(self, cmd: str) -> str | None:
        """A running worker was briefed on a target this main-window cmd
        also hits — duplicating a delegated scan burns budget twice
        (s1: main re-ran nmap -p- on app01 while w2 owned that very
        task). IPs and hostnames both count; advisory only, never a
        denial — the parent may legitimately verify worker findings."""
        ips = set(self._IP_RE.findall(cmd or ""))
        hosts = {h.lower() for h in self._HOST_LIKE.findall(cmd or "")}
        if not ips and not hosts:
            return None
        for w in self._workers.values():
            if w.status != "running":
                continue
            if (ips & set(self._IP_RE.findall(w.task))
                    or hosts & {h.lower()
                                for h in self._HOST_LIKE.findall(w.task)}):
                return w.id
        return None

    def _guide_hint(self, text: str, window: str | None) -> str:
        """Deterministic module push: the first unhinted module whose
        triggers match this cmd/output/denial text — once per module per
        window (shared `_guides_hinted` dedup)."""
        for mid in guides.triggers_for(text):
            hkey = f"{window or 'main'}:{mid}"
            if hkey in self._guides_hinted:
                continue
            self._guides_hinted.add(hkey)
            asyncio.create_task(log.ainfo(
                "guide hinted", module=mid, window=window or "main",
                session=self.sid))
            return (f"\nGUIDE: module '{mid}' covers this situation — "
                    f"lookup_guide(\"{mid}\") pulls the recipe "
                    "(verbatim commands).")
        return ""

    def _drain_observer_hints(self, result: str, a: dict,
                              window: str | None) -> str:
        """Observer channels on the guaranteed-read result:
        1. queued observer_hint events — pop-once, labeled unverified
        2. tag-matched field notes — pushed once per note per window
        3. hit feedback — progress within ~10 turns after a push → hit++
        Everything is bounded so the channel can never swamp a result."""
        out = result
        if window is None and self._worker_done:
            # worker lifecycle notice — parent-only: a worker's own results
            # must not be spammed with sibling status it can't act on
            out += f"\nWORKER DONE: {self._worker_done.pop(0)}"
        if window is None and self.state.pending_observer_hints:
            # parent-only too — a worker's frozen facts snapshot makes the
            # advisory useless to it, and it would eat the parent's copy
            hint = self.state.pending_observer_hints.pop(0)
            out += f"\nOBSERVER (unverified): {hint}"
        # hit feedback: did a note we pushed earlier actually help?
        if self._notes_pushed:
            done = []
            for nid, (ts_push, turn_push) in self._notes_pushed.items():
                if self.state.last_progress_ts > ts_push:
                    done.append(nid)
                    asyncio.create_task(self.client.lesson_hit(nid))
                elif self.state.exec_count - turn_push > 10:
                    done.append(nid)  # window expired without progress
            for nid in done:
                self._notes_pushed.pop(nid, None)
        # tag-matched push: a field note whose tags appear in this tool's
        # call/output is probably relevant right now — once per window
        if self.facts.field_notes:
            text = f"{a.get('type','')} {a.get('command','')} {result[:1500]}".lower()
            hinted = self._notes_hinted.setdefault(window or "main", set())
            for n in self.facts.field_notes:
                nid = int(n.get("id") or 0)
                if not nid or nid in hinted:
                    continue
                tags = [t.lower() for t in n.get("tags") or [] if len(t) > 2]
                if not tags or not any(t in text for t in tags):
                    continue
                hinted.add(nid)
                self._notes_pushed[nid] = (
                    self.state.last_progress_ts, self.state.exec_count)
                out += (f"\nFIELD NOTE (unverified): {n['text']}")
                break  # one note per result — never a wall of hints
        return out

    def _cred_spray_note(self, a: dict) -> str:
        """Advisory when one credential already failed on ≥2 hosts —
        password reuse is worth ONE try per host, but the spray pattern is
        a scope fact the model keeps re-testing (s84: deploy/web01-pw
        sprayed across .31/.32/.33 — every host rejected it). Advisory,
        not a denial: reuse could still work on an untried host. Pop-once
        per (secret, host) so the channel can't be spammed."""
        if a.get("type") not in ("exec_in_kali", "type_in_pane"):
            return ""
        cmd = str(a.get("command") or a.get("text") or "")
        for user, secret, tgt in facts_mod._cmd_creds(cmd):
            if not tgt or (secret, tgt) in self._spray_noted:
                continue
            # the secret is the spray signal — user can be '?' when the
            # extractor can't tie it (sshpass -p PW ssh u@host → ('?', PW))
            c = next((x for x in self.facts.creds
                      if x.secret == secret
                      and (user == "?" or x.user == user)), None)
            if not c:
                continue
            # prior failures EXCLUDING this target — tested_on/valid_on
            # update only in observe_output after the result lands
            failed = c.tested_on - c.valid_on - {tgt}
            if len(failed) >= 2:
                self._spray_noted.add((secret, tgt))
                proven = ",".join(sorted(c.valid_on)[:2]) or "none"
                return (f"\nNOTE: {user}-cred already auth-failed on "
                        f"{','.join(sorted(failed)[:3])} (valid on: {proven})"
                        " — the password is host-scoped, not reusable. "
                        "Rotate credentials instead of spraying.")
        return ""

    def _lookup_field_note(self, q: str, window: str | None) -> str | None:
        """Pull-side of the observer's knowledge: a field note whose tags or
        text overlap the query — labeled, capped, hit-tracked like a push."""
        if not self.facts.field_notes:
            return None
        terms = {w for w in re.findall(r"[a-z0-9_.-]{3,}", q.lower())}
        if not terms:
            return None
        best, best_score = None, 0
        for n in self.facts.field_notes:
            tags = {str(t).lower() for t in n.get("tags") or []}
            score = len(terms & tags) * 2
            body = str(n.get("text") or "").lower()
            score += sum(1 for t in terms if t in body)
            if score > best_score:
                best, best_score = n, score
        if best is None or best_score < 2:
            return None
        nid = int(best.get("id") or 0)
        if nid:
            self._notes_pushed[nid] = (
                self.state.last_progress_ts, self.state.exec_count)
        return f"FIELD NOTE (unverified): {best['text']}"

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
                             "value", "flag_key", "query", "url",
                             "name", "channel")
                    and isinstance(v, str)}
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
            # repeat-tracking: the identical denied command returning N times
            # reads as a fresh note each turn — escalate the count so the
            # model can't miss that this exact path is settled (s1: the same
            # deploy@10.1.10.32 attempt was denied 3× identically)
            sig_tgt = str(a.get("command") or a.get("query")
                          or a.get("url") or a.get("text")
                          or a.get("name") or a.get("channel") or "")[:80]
            sig = f"{a.get('type')}|{sig_tgt}"
            n = self._deny_counts[sig] = self._deny_counts.get(sig, 0) + 1
            if n >= 2:
                result += (f" (REPEATED ×{n} — this exact attempt was "
                           "already denied; it does not start working on "
                           "retry. Different user, host, or vector.)")
            # a denial's reason names the same triggers real output would —
            # `filtered:` fires the pivoting recipe even though no exec ran
            result += self._guide_hint(
                f"{a.get('command','')}\n{result}", window)
        # plan maintenance in the guaranteed-read channel: a plan untouched
        # >15min (or still absent after real work) means the agent lost its
        # thread — the context-block suffix was ignored for 40+ actions on
        # s65. Once per staleness window, parent turns only.
        if (window is None and self.state.autonomy_level >= 4
                and self.state.exec_count >= 3
                and time.time() - self._plan_stale_ping > _PLAN_STALE_S):
            age = time.time() - getattr(self.state, "plan_updated", 0.0)
            if not self.state.plan or age > _PLAN_STALE_S:
                self._plan_stale_ping = time.time()
                result += ("\nPLAN NOTE: " + (
                    "no roadmap set — create one via update_plan "
                    "(free action, keeps phases→steps straight)" if not
                    self.state.plan else
                    f"roadmap is {int(age / 60)}min stale — refresh via "
                    "update_plan: mark done steps, break the current "
                    "blocker into substeps (free action)"))
        # guaranteed-read channels last: observer hints + tag-matched field
        # notes land on whatever result the model is about to read — they
        # cannot scroll past unnoticed (pop-once, bounded)
        if spray := self._cred_spray_note(a):
            result += spray
        result = self._drain_observer_hints(result, a, window)
        return spoke, result

    # tokens that say nothing about WHICH flag a step belongs to
    _PLAN_GENERIC_TOKENS = frozenset({"flag", "flags", "submit", "check",
                                      "get", "read", "run", "the", "and",
                                      "via", "for", "from", "with", "into",
                                      "all", "find", "loot"})

    def _plan_push_card(self, tag: str) -> None:
        """Re-render the checklist card after system-side plan mutations
        (seed, flag auto-marks). Without this the feed froze on the last
        model save — s69 solved both flags while the card still showed
        them todo."""
        if not self.state.plan:
            return
        items = [dict(i) for i in self.state.plan]
        open_n = sum(1 for i in items if i["s"] != "done")
        meta = {**self._msg_meta(None), "plan": items, "open": open_n,
                "auto": tag}
        asyncio.create_task(self.client.send_chat(
            self.sid,
            f"**Plan ({tag}):** {open_n} open / {len(items)} steps",
            kind="action_report", meta=meta))
        asyncio.create_task(self.client.log_action(
            self.sid, "update_plan",
            {"items": items, "agent": "main", "auto": tag},
            {"open": open_n}))

    def _plan_mark_solved(self, flag_key: str) -> int:
        """A solved flag retires its roadmap steps — matching on the key's
        distinctive tokens ('ftp-flag' → 'ftp') keeps the checklist a live
        scoreboard instead of a stale intention list (s65: 'doing' stayed
        open 40 actions AFTER ftp-flag was submitted). Returns count marked."""
        if not self.state.plan:
            return 0
        toks = {t for t in re.split(r"[^a-z0-9]+", (flag_key or "").lower())
                if len(t) >= 3 and t not in self._PLAN_GENERIC_TOKENS}
        # generic numbered keys ('flag-1', 'host2') carry no distinctive
        # token — match the normalized key itself ('flag-1'→'flag1')
        # against normalized step text ('Solve flag-1'→'solveflag1').
        # Digits keep it specific; a bare 'flag' would match everything.
        norm = re.sub(r"[^a-z0-9]", "", (flag_key or "").lower())
        if norm.isalpha() or len(norm) < 4:
            norm = ""
        closed = 0
        for i in self.state.plan:
            if i["s"] == "done":
                continue
            txt = i["t"].lower()
            if (any(t in txt for t in toks)
                    or (norm and norm in re.sub(r"[^a-z0-9]", "", txt))):
                i["s"] = "done"
                closed += 1
        if closed:
            self.state.plan_updated = time.time()
        return closed

    _PLAN_RECON_TOKENS = frozenset({"recon", "enumerate", "enumeration",
                                    "scan", "discover", "map", "mapping",
                                    "foothold"})

    def _plan_close_recon(self) -> int:
        """First flag solve implies initial enumeration finished — retire a
        still-open recon/discovery step so the checklist tracks reality even
        when its steps don't name the flag (s84: 'Recon' stayed 'doing'
        while flag-1 was already submitted)."""
        if not self.state.plan:
            return 0
        closed = 0
        for i in self.state.plan:
            if i["s"] == "done":
                continue
            toks = set(re.split(r"[^a-z0-9]+", i["t"].lower()))
            if toks & self._PLAN_RECON_TOKENS:
                i["s"] = "done"
                closed += 1
        if closed:
            self.state.plan_updated = time.time()
        return closed

    def _plan_close_all(self) -> int:
        """all_solved → close every open step so the feed renders a finished
        checklist rather than an abandoned one."""
        closed = sum(1 for i in self.state.plan if i["s"] != "done")
        for i in self.state.plan:
            i["s"] = "done"
        if closed:
            self.state.plan_updated = time.time()
        return closed

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
            result = (f"denied: workers may only call "
                      f"{sorted(WORKER_TOOL_NAMES)} — report findings via "
                      "your last message, the parent coach relays them")
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
                budget = int(self.cfg.get("coach", {}).get("action_budget", 400))
                grace = int(self.cfg.get("coach", {}).get("action_grace", 80))
                grace_note = ""
                # workers carry their own bounds (turn/time caps) — the
                # parent's action budget must not starve their execs, and
                # worker execs must not drain the parent's budget either
                n_over = (self.state.exec_count - budget
                          if window is None else -1)
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
                    # scan saturation: >=3 recon scans on a host that still
                    # shows zero open ports is settled evidence — the next
                    # flag-variant rescan is a loop, not iteration (s84:
                    # w1 ran 4 nmap variants at a filtered host)
                    if re.search(
                            r"\b(nmap|masscan|rustscan|unicornscan)\b",
                            cmd or ""):
                        ips = self._IP_RE.findall(cmd or "")
                        hh = (self.facts.hosts.get(ips[-1])
                              if ips else None)
                        if hh and hh.scans >= 3 and not hh.ports:
                            await log.ainfo("scan saturated", session=self.sid,
                                            host=ips[-1], scans=hh.scans)
                            return spoke, (
                                f"denied: {ips[-1]} was scanned "
                                f"{hh.scans}x with zero open ports — "
                                "the host is settled as unreachable from "
                                "here. Reach it via a pivot (ssh creds on "
                                "an adjacent host) or move on; more "
                                "flag-variant scans change nothing.")
                    # rewrite guard: a solver that was written ≥2× and never
                    # ran (or ran clean) does NOT need another version — the
                    # model 'perfects' scripts forever otherwise. Deny before
                    # typing anything; a failed run unlocks the next rewrite.
                    wm = WRITE_RE.search(cmd)
                    if wm:
                        path = (wm.group(1) or wm.group(3) or "").strip("'\"")
                        ff = self.facts.files.get(
                            facts_mod.file_key(cmd, path))
                        n = ff.writes if ff else 0
                        last = ff.last_exit if ff else None
                        # externally-executed files (proven via a caps: fact,
                        # e.g. root cron) can't be "RUN" by us — demanding
                        # `python3 -u <path>` for a cron script is a dead end
                        external = any(path in c for c in self.facts.caps)
                        # vanished-file guard first: writes that never
                        # materialized (read reported absent after an
                        # exit-0 write) need the dir/host fixed, not a
                        # "never executed" lecture — mkdir+write and remote
                        # pushes (different file_key) stay allowed.
                        if (not external and ff and ff.missing
                                and not facts_mod.file_host(cmd)
                                and "mkdir" not in cmd):
                            await log.ainfo(
                                "write denied — file vanished",
                                session=self.sid, path=path,
                                writes=n, cmd=cmd[:120])
                            return spoke, (
                                f"denied: previous writes to {path} "
                                "never materialized — a later read "
                                "reported the file missing on THIS "
                                "host. Fix the cause, not the content: "
                                f"`ls -ld {path.rsplit('/', 1)[0] or '/'}`"
                                " (parent dir likely absent — mkdir it), "
                                "or the flag check reads a REMOTE vm's "
                                "fs — push the file there (ssh user@host "
                                "'cat > path' < local). Another local "
                                "rewrite lands nowhere.")
                        elif (not external and not (ff and ff.missing)
                                and n >= 2
                                and (last is None or last == 0)
                                and (ff is None or
                                     (ff.runs <= ff.write_run_seq
                                      and self.facts.checkfail_seq
                                      <= ff.write_check_seq))):
                            await log.ainfo("rewrite denied", session=self.sid,
                                            path=path, writes=n, cmd=cmd[:120])
                            # scripts are exercised by running them; reports
                            # and other deliverables are "exercised" by the
                            # flag check — telling the model to `python3 -u`
                            # a .txt produces a SyntaxError detour (s11).
                            verify = ("RUN it (python3 -u "
                                      f"{path})" if ff.kind == "script"
                                      else "VERIFY it — re-run the flag "
                                           f"check (check_flag) or `cat "
                                           f"{path}` to confirm content")
                            return spoke, (
                                f"denied: {path} was already written {n}x and "
                                f"the current version was never exercised — "
                                f"{verify}. Another rewrite is only useful "
                                f"after new evidence: a run, a failed check, "
                                f"or a crash.")
                    # read-loop guard: re-reading the same file produces
                    # identical output — settled facts the model keeps
                    # re-deriving (seen live: 6x `cat nmap.txt | grep …`
                    # variants instead of connecting to the found service).
                    # The output-sig NOTE below is only a hint — the 4th
                    # read of the SAME path is denied before typing.
                    read_tgt = facts_mod.read_target(cmd)
                    if read_tgt:
                        rf = self.facts.files.get(
                            facts_mod.file_key(cmd, read_tgt))
                        n = rf.reads if rf else 0
                        if n >= 3:
                            await log.ainfo("reread denied",
                                            session=self.sid, path=read_tgt,
                                            reads=n, cmd=cmd[:120])
                            # carry what we already extracted — 'settled'
                            # alone leaves the model blind to WHAT it knows
                            # (s46 retried cat backup.sh 4x post-restart)
                            base = read_tgt.rsplit("/", 1)[-1]
                            loot = next((f[5:] for f in self.facts.findings
                                         if f.startswith(f"loot:{base}")), "")
                            hint = (f" — extracted already: {loot}"
                                    if loot else
                                    " — need freshness, not content? "
                                    "`sha256sum`/`stat` it (not a read)")
                            # compound `producer && cat file` aborts at the
                            # read — the run never executes, the file stays
                            # stale, the next compound denies again (s54).
                            # Say how to refresh: run the producer ALONE.
                            return spoke, (
                                f"denied: {read_tgt} was already read "
                                f"{n}x with the same result — its contents "
                                f"are settled facts{hint} "
                                f"To REFRESH the file, run its producer "
                                f"as a separate command first, then read. "
                                f"(see ALREADY_DONE). "
                                f"Take a DIFFERENT action toward the flag: "
                                f"connect to a discovered service, use "
                                f"credentials you found, or submit a flag.")
                    bad_ip = self._foreign_ip(cmd)
                    bad_host = (self._foreign_host(cmd)
                                if self._scope_locked else None)
                    if bad_ip or bad_host:
                        known = [f"{t.get('name')}={t.get('ip')}"
                                 for t in (self.ctx.get("quest", {}).get(
                                     "targets") or []) if t.get("ip")]
                        bad = bad_ip or bad_host
                        await log.ainfo("scope denied", session=self.sid,
                                        target=bad, cmd=cmd[:120],
                                        locked=self._scope_locked)
                        if self._scope_locked:
                            if self._scope_required:
                                return spoke, (
                                    f"denied: {bad} — the engagement scope "
                                    "is NOT SET yet. The operator must "
                                    "declare the authorized whitelist "
                                    "(engagement scope dialog / POST "
                                    "/sessions/{id}/scope) before any "
                                    "target is reachable — ask for it "
                                    "instead of probing.")
                            nets = ", ".join(str(n) for n in
                                             self._allowed_nets[:8])
                            return spoke, (
                                f"denied: {bad} is outside the AUTHORIZED "
                                f"engagement scope — hard ROE boundary, do "
                                f"NOT retry with variations. In scope: "
                                f"nets=[{nets}] "
                                f"hosts=[{', '.join(sorted(self._scope_hosts)[:8]) or '-'}]"
                                f"{f' ports={sorted(self._scope_ports)}' if self._scope_ports else ''}. "
                                "Only the operator can widen scope "
                                "(engagement settings) — pick an in-scope "
                                "target instead.")
                        return spoke, (
                            f"denied: {bad} is no known target — connects "
                            f"to it hang and eat the pane. KNOWN TARGETS: "
                            f"{'; '.join(known) or '(resolve names via getent)'}. "
                            f"A host is only allowed once its IP appears in "
                            f"tool output (scan result, getent, logs).")
                    # infra-backoff: after repeated backend/qga errors, let
                    # only a periodic probe through instead of burning turns
                    # retyping payloads into a dead channel
                    if self._infra_errors >= 3:
                        since_probe = time.time() - self._infra_last_probe
                        if since_probe < 45:
                            return spoke, (
                                "denied: kali exec channel unreachable "
                                f"({self._infra_errors} consecutive infra "
                                "errors — qga/backend down or VM "
                                "restarting). Wait ~45s, then probe with a "
                                "cheap `echo ok`. Do NOT retype payloads — "
                                "everything typed now is lost.")
                        self._infra_last_probe = time.time()
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
                    # API-level failures only (qga dead / VM not running /
                    # transport) — denied statuses are policy, not outages
                    if res.get("error") and res.get("status") != "denied" \
                            and re.search(_INFRA_ERR, res["error"]):
                        self._infra_errors += 1
                    else:
                        self._infra_errors = 0
                    if res.get("status") == "denied" or res.get("error") or res.get("busy"):
                        # never actually typed → a stale entry could mislabel a
                        # user-typed identical command
                        self._coach_cmds.pop()
                    else:
                        # parent-only budget accounting — workers have their
                        # own turn/time caps; their execs must not eat the
                        # parent's exploration budget (s84: a busy worker
                        # pool would hard-deny the parent's own chain)
                        if window is None:
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
                        # a fresh reachability denial must also ride the
                        # guaranteed-read tool result — a worker's facts
                        # snapshot is frozen at spawn, so only this note
                        # tells it mid-flight to stop rescanning a host
                        # that is filtered from its vantage (s84: w1 ran
                        # 4 nmap variants at an isolated app01)
                        seen = self._denial_seen.setdefault(
                            window or "main", set())
                        for dn in self.facts.denials:
                            if dn in seen or not dn.startswith(
                                    ("filtered:", "unreachable:")):
                                continue
                            seen.add(dn)
                            tgt, _, vant = dn.split(":", 1)[1].partition("@")
                            result += (
                                f"\nNOTE: {tgt} is unreachable/filtered from"
                                f" {vant} — recorded as dead end "
                                f"blocked:{dn}. Rescanning from this vantage"
                                " won't change it: reach the host via a "
                                "pivot (ssh creds from an adjacent host) or"
                                " move on.")
                            break
                        # deterministic guide push: command+output triggers
                        # name the recipe module that covers this situation —
                        # a weak model should not have to know what to search
                        # for; one hint per module per session keeps it quiet
                        result += self._guide_hint(
                            f"{cmd}\n{out[:3000]}", window)
                        # evidence re-read loop: the per-file deny (n>=3,
                        # pre-exec) misses loops that re-read DIFFERENT
                        # already-read files under one dir, and glob/var
                        # reads read_target can't key at all (s1-eval: 6
                        # turns of cat/grep/ls over ~/evidence/* looked like
                        # a stall). Soft advisory only — never a deny.
                        rt = facts_mod.read_target(cmd)
                        bump, rkey = False, None
                        if rt:
                            rf2 = self.facts.files.get(
                                facts_mod.file_key(cmd, rt))
                            # observe_output already counted this exec —
                            # reads>=2 means this file was seen before
                            bump = rf2 is not None and rf2.reads >= 2
                            rkey = rt.rsplit("/", 1)[0] or "/"
                        elif (self._READ_VERB.search(cmd)
                                and not self._WRITE_HINT.search(cmd)
                                and (ps := self._PATHISH.findall(cmd))):
                            # for-loop/glob shape — bucket by dir so it
                            # shares the counter with verified re-reads
                            p = ps[-1].lstrip("~")
                            bump = True
                            rkey = p.rsplit("/", 1)[0] or "/"
                        if bump and rkey:
                            k = f"{window or 'main'}|rr:{rkey}"
                            n = self._read_counts[k] = \
                                self._read_counts.get(k, 0) + 1
                            if n >= 3:
                                result += (
                                    f"\nNOTE: {n} re-reads in/along "
                                    f"'{rkey}' — contents already read are "
                                    "settled in your history. Synthesize "
                                    "findings or act on them (connect to a "
                                    "service, use a cred); new information "
                                    "needs NEW commands.")
                        # literal-var footgun: `sshpass -p '$pass'` passes
                        # the literal text "$pass" — single quotes stop
                        # expansion, so the auth failure that follows looks
                        # like a wrong cred although it was never tried
                        # (s1: cost a full turn + a retry loop)
                        if re.search(r"sshpass\s+-p\s+['\"]\$", cmd):
                            result += (
                                "\nNOTE: `-p '$…'` — single quotes make "
                                "sshpass receive the LITERAL text, not "
                                "the variable's value. Put the real "
                                "password after -p (or double-quote an "
                                "exported var) and retry.")
                        # main window redoing a running worker's target —
                        # the exec already ran (advisory only); once per
                        # (worker, target) pair so it's a hint, not a nag
                        if window is None and (
                                dup := self._worker_target_dup(cmd)):
                            tgt = next(
                                (ip for ip in self._IP_RE.findall(cmd)
                                 if ip in self._IP_RE.findall(
                                     self._workers[dup].task)),
                                cmd[:40])
                            if (dup, tgt) not in self._dup_noted:
                                self._dup_noted.add((dup, tgt))
                                result += (
                                    f"\nNOTE: {dup} is already working "
                                    f"on {tgt} — collect its report "
                                    f"with collect_agent(\"{dup}\") "
                                    "instead of duplicating its scans; "
                                    "spend this window on another "
                                    "angle.")
                        # ledger-driven orchestrator hint: recon on a
                        # surface the ledger already tracks as untested/
                        # testing while a worker slot is free — delegate
                        # instead of scanning serially in the main window
                        # (advisory once per ip, never a deny)
                        if (window is None
                                and self.state.subagents_enabled
                                and facts_mod.RECON_RE.search(cmd)):
                            max_w = int(self.cfg.get("coach", {}).get(
                                "max_workers", 4))
                            free = max_w - sum(
                                1 for w in self._workers.values()
                                if w.status == "running")
                            if free > 0:
                                for ip in self._IP_RE.findall(cmd):
                                    row = next(
                                        (r for k, r in
                                         self.state.coverage.rows.items()
                                         if k == ip
                                         or k.startswith(f"{ip}:")), None)
                                    key = f"orch:{ip}"
                                    if (row and row["outcome"] in
                                            ("untested", "testing")
                                            and key not in self._dup_noted):
                                        self._dup_noted.add(key)
                                        result += (
                                            f"\nNOTE: {ip} is a coverage "
                                            f"row ({row['outcome']}) and a "
                                            "worker slot is free — "
                                            "spawn_agent it with a role "
                                            "instead of scanning it "
                                            "serially here.")
                                        break
                        # settled-surface advisory: an exec against a
                        # coverage row that already closed (confirmed /
                        # tested_clean) re-tests settled work — the ledger
                        # is the closure discipline, not the pane
                        for ip in self._IP_RE.findall(cmd):
                            settled = next(
                                (r for k, r in
                                 self.state.coverage.rows.items()
                                 if (k == ip or k.startswith(f"{ip}:"))
                                 and r["outcome"] in ("confirmed",
                                                      "tested_clean")),
                                None)
                            skey = f"settled:{ip}:{window or 'main'}"
                            if (settled and skey not in self._dup_noted
                                    and facts_mod.RECON_RE.search(cmd)):
                                self._dup_noted.add(skey)
                                result += (
                                    f"\nNOTE: coverage for {ip} closed as "
                                    f"{settled['outcome']}"
                                    f"{' — ' + settled['evidence'][:60] if settled['evidence'] else ''}"
                                    " — re-testing re-proves settled "
                                    "work; spend the action on an open "
                                    "surface (list_coverage).")
                                break
                    elif code is None:
                        err_hint = res.get("err") or ""
                        if err_hint and err_hint not in out:
                            result = f"{out[:1500]}\n[{err_hint}]"[:1900]
                        else:
                            result = out[:1900] or "still running"
                        if res.get("error") and res.get("status") != "denied" \
                                and re.search(_INFRA_ERR, res["error"]):
                            # API-level failure (qga dead / VM restarting /
                            # backend hiccup) — the command never reached the
                            # pane. Without this note the model treats it as
                            # a command error and retypes variants forever.
                            result += (
                                "\n[INFRA: exec channel error — the command "
                                "never ran. Likely qga/VM/backend restart. "
                                "Wait ~30-45s and probe with `echo ok`, then "
                                "RETRY the same command — transport failure "
                                "is not a denial; the payload is still owed.]")
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
                        ff = self.facts.files.get(
                            facts_mod.file_key(cmd, path))
                        n = ff.writes if ff else 0
                        if n >= 2 and ff.missing:
                            result += (
                                f"\nNOTE: {n} writes to {path} never "
                                "materialized — a read reported it missing. "
                                f"Verify NOW: `ls -l {path}`. Absent → the "
                                "parent dir doesn't exist on THIS host "
                                "(`ls -ld "
                                f"{path.rsplit('/', 1)[0] or '/'}`, mkdir "
                                "it), or the flag check wants the file on "
                                "a REMOTE vm — push it via ssh/scp.")
                        elif n >= 2:
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
                # already-accepted resubmits burn a turn for zero gain —
                # s46 submitted flag-4 four times (once at 01:59, thrice
                # more post-restart while 'ok' kept saying solved)
                if ff is not None and ff.accepted:
                    return spoke, (
                        f"denied: `{val[:80]}` is already accepted — flag "
                        f"solved. Re-submitting scores nothing; move to the "
                        f"NEXT objective.")
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
                if res.get("correct"):
                    marked = self._plan_mark_solved(res.get("flag_key") or "")
                    marked += self._plan_close_recon()
                    if marked:
                        result += f"; plan: {marked} step(s) auto-marked done"
                        self._plan_push_card("auto-mark")
                if res.get("all_solved"):
                    if self._plan_close_all():
                        self._plan_push_card("all-solved")
                    result += "; all_solved — plan closed"
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
                if not res.get("correct"):
                    # a failed check is fresh evidence — rewrites of the
                    # deliverable producer are informed iteration, not
                    # 'perfecting' (s54: report.sh ran clean but its output
                    # was wrong; only the check knew)
                    self.facts.checkfail_seq += 1
                verdict = ("verified — flag solved" if res.get("correct")
                           else f"not satisfied ({res.get('detail') or res.get('error') or 'check failed'})")
                result = f"check {key} → {verdict}"
                text = f"Ran server check for `{key}` → **{verdict}**"
                if res.get("correct"):
                    marked = self._plan_mark_solved(key)
                    marked += self._plan_close_recon()
                    if marked:
                        result += f"; plan: {marked} step(s) auto-marked done"
                        self._plan_push_card("auto-mark")
                if res.get("all_solved"):
                    if self._plan_close_all():
                        self._plan_push_card("all-solved")
                    result += "; all_solved — plan closed"
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
                cap = int(self.cfg.get("coach", {}).get("wait_max_s", 600))
                n = max(1, min(n, cap))
                # don't sleep into a dying turn — the outer wait_for budget
                # would cancel mid-wait and the model never sees the result.
                # A worker waits against ITS OWN time cap, not the parent's
                # (both can run concurrently — the flag is parent-turn state)
                if window:
                    w = self._workers.get(window)
                    deadline = (w.started + float(
                        self.cfg.get("coach", {}).get(
                            "worker_time_cap_s", 3600))) if w else None
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
            raw = a.get("items") or a.get("plan") or []
            if "ptg" in self._ablate:
                # ablation: structured fields collapse to flat {t,s} —
                # the task-graph layer (deps/ready/marks) never engages
                raw = [{"t": i.get("t", ""), "s": i.get("s", "todo")}
                       if isinstance(i, dict) else i for i in raw]
            items = normalize_plan(raw)
            target = (self._workers[window].plan
                      if window and window in self._workers
                      else self.state.plan)
            unchanged = items == target
            target.clear()
            target.extend(items)
            if not window:
                self.state.plan_updated = time.time()
            open_n = sum(1 for i in items if i["s"] != "done")
            verb = ("plan unchanged — no need to re-send identical plans; "
                    "update when steps complete or the approach pivots"
                    if unchanged else "plan saved")
            result = (f"{verb} — {len(items)} steps ({open_n} open): "
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
        elif t in ("record_coverage", "update_coverage", "create_note"):
            # engagement bookkeeping — agent-declared coverage outcomes and
            # shared notes. Writer actions log to coach_actions and replay
            # on restart (like update_plan); workers contribute via their
            # report merge, they never call these mid-run.
            agent = window or "main"
            if t == "create_note":
                r = self.state.pad.create(
                    a.get("key"), a.get("text") or a.get("content") or "",
                    owner=agent)
            elif t == "update_coverage":
                r = self.state.coverage.update(
                    a.get("surface"), a.get("outcome") or "testing",
                    a.get("evidence") or "", owner=agent)
            else:
                r = self.state.coverage.record(
                    a.get("surface"), a.get("area") or "",
                    a.get("outcome") or "testing",
                    a.get("evidence") or "", owner=agent)
            if r.get("error"):
                result = f"error: {r['error']}"
            elif t == "create_note":
                result = f"note {r['ok']}: {r['key']}"
            else:
                result = (f"coverage {r['ok']}: {r['surface']} → "
                          f"{r['outcome']}")
            asyncio.create_task(self.client.log_action(
                self.sid, t, {**{k: v for k, v in a.items()
                                 if not k.startswith("_")},
                              "agent": agent}, r))
        elif t == "list_coverage":
            want = (a.get("outcome") or "").strip()
            rows = [r for r in self.state.coverage.rows.values()
                    if not want or r["outcome"] == want]
            if not rows:
                result = ("no coverage rows"
                          + (f" with outcome={want}" if want else " yet"))
            else:
                lines = []
                for r in rows:
                    line = f"{r['surface']} → {r['outcome']}"
                    if r["area"]:
                        line += f" [{r['area']}]"
                    if r["owner"] != "main":
                        line += f" @{r['owner']}"
                    if r["evidence"]:
                        line += f" — {r['evidence'][:70]}"
                    lines.append(line)
                result = "\n".join(lines)[:1200]
        elif t == "list_notes":
            result = (self.state.pad.render(1200) or
                      "shared notes pad is empty")
        elif t == "record_finding":
            # typed finding — create or validation-update; rides
            # coach_actions so a restart replays the finding set like it
            # replays the ledger (see ledger_log → apply_finding)
            row = self.facts.apply_finding(a, owner=window or "main")
            if row is None:
                result = (f"error: no finding "
                          f"{a.get('id')!r} — ids come from earlier "
                          "record_finding results")
            else:
                result = (f"finding {row['id']} ({row['status']}): "
                          f"{row['title']}"
                          + (f" @{row['host']}" if row['host'] else "")
                          + (" — DEMOTED to candidate: confirmed needs "
                             "≥12 chars of concrete evidence"
                             if (a.get("status") == "confirmed"
                                 and row["status"] == "candidate") else ""))
            asyncio.create_task(self.client.log_action(
                self.sid, "record_finding",
                {**{k: v for k, v in a.items() if not k.startswith("_")},
                 "agent": window or "main"},
                {"id": row["id"] if row else None,
                 "status": row["status"] if row else None}))
        elif t == "build_report":
            md = self.facts.report(
                scope=self.ctx.get("scope"),
                coverage_rows=self.state.coverage.rows,
                title=str(a.get("title") or "Penetration Test Report")[:80])
            if len(md) > 3200:
                md = md[:3180] + "\n…[truncated — backend GET " \
                    "/sessions/{id}/report carries the full version]"
            result = (md +
                      "\n\n---\nWrite this to the report path via "
                      "write_file (or heredoc) — report-checking flags "
                      "grep the file on disk.")
        elif t == "lookup_guide":
            # pull a technique recipe — internal knowledge consult, costs no
            # exec budget, nothing shown to the trainee (the recipe lands in
            # the model's tool reply where the next turn can act on it)
            q = str(a.get("query") or a.get("content") or "")[:120]
            win = window or "main"
            mid = guides.resolve_id(q)
            fetched = self._guide_fetched.setdefault(win, set())
            if mid and mid in fetched:
                # repeat pull of a static recipe — the content is already
                # in this window's history; re-paying ~2k tokens teaches
                # the model to re-fetch instead of re-using
                result = (f"module '{mid}' already loaded — reuse the recipe "
                          "you have; spend actions on the target instead")
            else:
                if mid:
                    fetched.add(mid)
                result = guides.lookup(q)
            # union search: observer field notes ride the same pull channel
            # — one tool answers with curated modules AND unverified session
            # lessons (always labeled). A module hit still appends a matching
            # note: the recipe is general, the note is this session's scar.
            note = self._lookup_field_note(q, window)
            if result.startswith(("error:", "multiple")):
                if note is not None:
                    result = note
            elif note is not None:
                result += f"\n\n{note}"
            asyncio.create_task(self.client.log_action(
                self.sid, "lookup_guide",
                {"query": q, "agent": window or "main"},
                {"hit": not result.startswith(("error:", "multiple"))}))
        elif t == "record_lesson":
            # agent-authored session knowledge — lands in FACTS.lessons,
            # rendered to parent AND future worker spawns, and replayed
            # from coach_actions on restart (bridges the context-loss gap
            # for hard-won facts like 'app01 needs Bearer from config.js')
            txt = (a.get("text") or a.get("content") or "")[:160]
            if not txt.strip():
                return spoke, "error: empty lesson"
            n = self.facts.add_lesson(txt, window or "main")
            asyncio.create_task(self.client.log_action(
                self.sid, "record_lesson",
                {"text": txt, "agent": window or "main"},
                {"count": n}))
            result = (f"lesson recorded ({n} kept) — visible in FACTS "
                      "lessons: to you and future workers")
        elif t == "threat_model":
            # engagement threat-model card — attacker/boundaries/assets;
            # merges field-wise (an amend keeps the rest), replayed from
            # ledger_log like coverage so a restart keeps the card
            tm = self.state.threat_model
            for k in ("attacker", "boundaries", "assets"):
                if v := str(a.get(k) or "").strip():
                    tm[k] = v[:200]
            if not tm:
                result = "error: threat_model needs at least one of attacker/boundaries/assets"
            else:
                asyncio.create_task(self.client.log_action(
                    self.sid, "threat_model",
                    {**tm, "agent": window or "main"},
                    {"fields": sorted(tm)}))
                result = (f"threat model recorded — "
                          f"attacker={tm.get('attacker', '-')} | "
                          f"boundaries={tm.get('boundaries', '-')} | "
                          f"assets={tm.get('assets', '-')} "
                          "— workers see this card at spawn")
        elif t == "search_memory":
            # long-term success-case memory — top-3 distilled attack paths
            # from past sessions. Guidance, never evidence: the model must
            # verify a path fits THIS target before following it.
            q = str(a.get("query") or a.get("content") or "")[:200]
            try:
                res = await self.client.search_memory(self.sid, q)
            except (TimeoutError, httpx.HTTPError) as e:
                res = {"error": str(e)}
            hits = (res or {}).get("hits") or []
            if (res or {}).get("error"):
                result = (f"error: memory search failed — "
                          f"{str(res['error'])[:120]}")
            elif not hits:
                result = ("no memory hits — this situation is new ground; "
                          "proceed with fundamentals (enum → vectors → "
                          "proof) and record_play the chain when it works")
            else:
                parts = []
                for h in hits:
                    steps = "\n".join(
                        f"  {i + 1}. {s}"
                        for i, s in enumerate((h.get("steps") or [])[:10]))
                    parts.append(
                        f"ap{h['id']} [conf {h.get('confidence', 0.5):.2f}] "
                        f"{h.get('title', '')}\n{steps}"
                        + (f"\n  → {h['outcome']}" if h.get("outcome") else ""))
                result = ("MEMORY — proven paths from past sessions "
                          "(adapt to THIS target; verify before trusting):\n"
                          + "\n\n".join(parts)
                          + "\n— followed one? report the outcome via "
                          "play_outcome(play_id, ok) once it resolves")
            asyncio.create_task(self.client.log_action(
                self.sid, "search_memory",
                {"query": q, "agent": window or "main"},
                {"hits": len(hits)}))
        elif t == "record_play":
            # success-case write — distills the winning chain into
            # long-term memory; backend sanitizes secrets + generalizes
            # IPs so the memory teaches moves, not loot
            try:
                res = await self.client.record_play(
                    self.sid, str(a.get("title") or "")[:160],
                    a.get("tags") or [], a.get("steps") or [],
                    str(a.get("outcome") or "")[:240])
            except (TimeoutError, httpx.HTTPError) as e:
                res = {"error": str(e)}
            if res and res.get("id"):
                result = (f"play stored as ap{res['id']} — future sessions "
                          "retrieve it via search_memory")
            else:
                result = ("error: play rejected — "
                          + str((res or {}).get("detail")
                                or (res or {}).get("error")
                                or "sanitize/validation failure")[:160])
            asyncio.create_task(self.client.log_action(
                self.sid, "record_play",
                {"title": str(a.get("title") or "")[:160],
                 "agent": window or "main"},
                {"ok": bool(res and res.get("id"))}))
        elif t == "play_outcome":
            # reinforcement feedback for a memory hit the model followed
            try:
                pid = int(a.get("play_id") or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid <= 0:
                result = ("error: play_outcome needs a numeric play_id "
                          "from a search_memory hit")
            else:
                ok = bool(a.get("ok"))
                asyncio.create_task(self.client.play_feedback(pid, ok))
                result = (f"feedback recorded — memory path ap{pid} "
                          f"{'reinforced' if ok else 'marked stale'}")
        elif t == "run_playbook":
            # bounded macro-chain — one validated command on the 'pb'
            # pane, parsed back into coverage rows + notes. Scope guard
            # is identical to exec_in_kali: the built line gets checked
            # BEFORE anything is typed.
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            elif not (pb := playbooks.get(str(a.get("name") or ""))):
                result = (f"error: unknown playbook — known: "
                          f"{playbooks.describe()}")
            elif not isinstance(a.get("args") or {}, dict):
                result = ("error: run_playbook args must be an object "
                          f"— {pb.args_hint()}")
            else:
                args = {str(k)[:24]: str(v)[:160]
                        for k, v in (a.get("args") or {}).items()}
                missing = [k for k in pb.required if not args.get(k)]
                have = set((self.ctx.get("session_tools") or "").split())
                lack = [b for b in pb.needs if b not in have]
                if missing:
                    result = (f"error: {pb.name} missing "
                              f"{', '.join(missing)} — {pb.args_hint()}")
                elif lack:
                    result = (f"error: {pb.name} needs "
                              f"{', '.join(lack)} — not in KALI_TOOLS "
                              "(probed at deploy, so it is NOT installed)")
                else:
                    try:
                        cmd = pb.build(args)
                    except (ValueError, TypeError, KeyError) as e:
                        # a bad arg (port 'eighty', empty path) is a
                        # model error, not a crash — the turn continues
                        cmd = ""
                        result = (f"error: {pb.name} arg invalid — {e}; "
                                  f"{pb.args_hint()}")
                    bad = ((self._foreign_ip(cmd)
                            or (self._foreign_host(cmd)
                                if self._scope_locked else None))
                           if cmd else None)
                    if cmd and bad:
                        # no branch-internal log_denial — the "denied:"
                        # prefix makes _dispatch's central audit write the
                        # row (one denial, one row; repeat-tracking rides
                        # along for free)
                        result = (f"denied: {pb.name} would reach {bad} "
                                  "— outside the authorized scope; pick "
                                  "an in-scope target")
                    elif cmd:
                        self._coach_cmds.append((cmd, time.time()))
                        await self.client.send_activity(
                            self.sid, f"playbook {pb.name} running on pb pane",
                            agent=window or "main")
                        try:
                            res = await self.client.exec_in_kali(
                                self.sid, cmd,
                                window=playbooks.PLAYBOOK_WINDOW)
                        except (TimeoutError, httpx.HTTPError) as e:
                            self._coach_cmds.pop()
                            res = {"error": str(e)}
                        out = (res.get("out") or res.get("err")
                               or res.get("error") or "")
                        code = res.get("exitcode")
                        self.state.add_command(time.time(), cmd,
                                               from_coach=True)
                        self.state.commands[-1].exit_code = code
                        self.facts.observe_output(cmd, out, code)
                        merged = []
                        parsed = pb.parse(out) or {}
                        for c in parsed.get("coverage") or []:
                            r = self.state.coverage.record(
                                c.get("surface"), c.get("area") or pb.name,
                                c.get("outcome") or "testing",
                                c.get("evidence") or "",
                                owner=window or "main")
                            if r.get("ok"):
                                merged.append(c.get("surface") or "?")
                        for n in parsed.get("notes") or []:
                            self.state.pad.create(
                                n.get("key"), n.get("text") or "",
                                owner=window or "main")
                        asyncio.create_task(self.client.log_action(
                            self.sid, "run_playbook",
                            {"name": pb.name, "args": args,
                             "agent": window or "main"},
                            {"coverage": len(merged)}))
                        tail = percept.normalize(
                            cmd, out, code,
                            timed_out=bool(res.get("timed_out"))).reply[:900]
                        result = (f"playbook {pb.name} done "
                                  f"(exit={code}, {len(merged)} coverage "
                                  f"rows: {', '.join(merged[:10]) or '-'})\n"
                                  f"{tail}")
        elif t == "search_exploitdb":
            # offline exploit lookup — searchsploit's own CSV index on the
            # Kali box, visible exec like playbooks (no scope check needed:
            # it reads a local file, reaches no target). Honest needs-gate
            # on the deploy-time tool probe.
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            elif not (q := str(a.get("query") or a.get("content")
                                 or "").strip()[:80]):
                result = "error: empty query"
            elif "searchsploit" not in set(
                    (self.ctx.get("session_tools") or "").split()):
                result = ("error: searchsploit not in KALI_TOOLS — the "
                          "deploy probe did not find the exploitdb package; "
                          "manual fallback: grep the csv or ask the "
                          "operator to install it")
            else:
                t_flag = " -t" if a.get("title_only") else ""
                cmd = (f"searchsploit --json --disable-color{t_flag} "
                       f"-- {shlex.quote(q)}")
                self._coach_cmds.append((cmd, time.time()))
                try:
                    res = await self.client.exec_in_kali(
                        self.sid, cmd, window=playbooks.PLAYBOOK_WINDOW)
                except (TimeoutError, httpx.HTTPError) as e:
                    self._coach_cmds.pop()
                    res = {"error": str(e)}
                out = (res.get("out") or res.get("err")
                       or res.get("error") or "")
                code = res.get("exitcode")
                self.state.add_command(time.time(), cmd, from_coach=True)
                self.state.commands[-1].exit_code = code
                asyncio.create_task(self.client.log_action(
                    self.sid, "search_exploitdb",
                    {"arg": q, "agent": window or "main"},
                    {"exitcode": code}))
                result = _render_searchsploit(out, code, q)
        elif t == "search_technique":
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            else:
                result = await self._search_technique(
                    str(a.get("query") or a.get("content") or ""),
                    str(a.get("source") or "auto"), window)
        elif t in ("channel_open", "channel_send", "channel_read",
                   "channel_close"):
            if level < 4:
                result = f"denied: autonomy level {level} < 4"
            else:
                result = await self._channel_dispatch(t, a, window)
        elif t in ("web_search", "web_fetch", "query_vuln_db", "rss_feed"):
            # key-free research, gated on the session's kali_internet flag —
            # the same flag wires Kali's second NIC, so the gate doubles as
            # lab isolation (resync() refreshes ctx → mid-session toggles
            # propagate). Denial text teaches the alternative; CACHED:/
            # error: results stay honest so a retry reads as a retry.
            if not self.ctx.get("session", {}).get("kali_internet"):
                alt = ("search_exploitdb/search_technique (they work "
                       "offline)" if t in ("query_vuln_db", "rss_feed")
                       else "local tools (nmap/wordlists/guides)")
                result = (f"denied: web — offline lab (kali_internet=false): "
                          f"no uplink this session. web_fetch runs from the "
                          "coach host and cannot reach range targets either "
                          "— fetch in-lab pages with exec_in_kali curl/wget "
                          f"instead. Use {alt} or ask the operator to "
                          "enable internet on the session.")
            elif t == "web_search":
                q = str(a.get("query") or a.get("content") or "")
                result = await self._web.search(
                    q, _safe_int(a.get("max_results"), 6))
            elif t == "web_fetch":
                u = str(a.get("url") or a.get("content") or "")
                result = await self._web.fetch(u)
            elif t == "query_vuln_db":
                result = await self._research.vuln(
                    str(a.get("query") or a.get("content") or ""))
            else:
                result = await self._research.feed(
                    str(a.get("feed") or a.get("query")
                        or a.get("content") or ""),
                    _safe_int(a.get("count"), 5))
            if not result.startswith(("denied:", "error:")):
                # same recipe push exec output gets — a fetched page naming
                # 'jwt'/'pivot' should pull the matching module once
                arg = str(a.get("query") or a.get("url")
                          or a.get("feed") or "")
                result += self._guide_hint(f"{arg}\n{result[:3000]}", window)
                if t == "web_fetch":
                    result += await self._scan_flags(
                        result, "web_fetch", window)
            asyncio.create_task(self.client.log_action(
                self.sid, t,
                {"arg": str(a.get("query") or a.get("url")
                            or a.get("feed") or "")[:200],
                 "agent": window or "main"},
                {"preview": result[:200],
                 "ok": not result.startswith(("denied:", "error:"))}))
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
        max_w = int(self.cfg.get("coach", {}).get("max_workers", 4))
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
        role = str(a.get("role") or "general").strip().lower()
        if role not in WORKER_ROLES or "roles" in self._ablate:
            role = "general"
        done_when = str(a.get("done_when") or "").strip()[:140]
        # PTG binding — a spawn against a plan task claims it (ow=wid,
        # s=doing); after MAX_ATTEMPTS bound workers the task must be
        # re-planned, not re-briefed (3 failed identical attacks is a
        # dead vector, not bad luck)
        task_id = str(a.get("task_id") or "").strip()[:16]
        bound = None
        if task_id and "ptg" in self._ablate:
            task_id = ""   # ablation: no task-graph binding exists
        if task_id:
            bound = ptg.by_id(self.state.plan, task_id)
            if bound is None:
                return (f"error: no plan task {task_id!r} — ids come from "
                        "update_plan items (they need an 'id' field)")
            if bound.get("ow") and bound.get("s") == "doing":
                return (f"denied: task {task_id} is already owned by "
                        f"{bound['ow']} — collect that worker or reassign "
                        "the task via update_plan")
            if int(bound.get("at") or 0) >= ptg.MAX_ATTEMPTS:
                return (f"denied: task {task_id} already consumed "
                        f"{bound['at']} worker attempts — update_plan it "
                        "blocked/abandoned or re-approach it before "
                        "spawning again")
            bound["at"] = int(bound.get("at") or 0) + 1
            bound["s"] = "doing"
            bound["ow"] = wid
        w = _Worker(id=wid, task=task[:500], started=time.monotonic(),
                    role=role, done_when=done_when, task_id=task_id)
        self._workers[wid] = w
        self._push_agents()
        w.task_obj = asyncio.create_task(self._worker_loop(w))
        # audit: the roster lifecycle is coach-internal — without a row the
        # backend (and any post-restart resync) never knew workers existed
        asyncio.create_task(self.client.log_action(
            self.sid, "spawn_agent",
            {"worker_id": wid, "task": task[:200], "role": role},
            {"spawned": wid}))
        return (f"spawned {wid} — \"{task[:120]}\". It works autonomously on "
                f"its own pane ({wid}); continue your own work and read its "
                f"report with collect_agent(\"{wid}\") when you need it. "
                "Keep delegated tasks bounded — a -p- scan ties a worker "
                "down for an hour; prefer top-ports or targeted probes.")

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
            wait_s = float(self.cfg.get("coach", {}).get("collect_wait_s", 240))
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
                # belt: if the task was already past its loop the Cancel
                # never reaches _finish_worker — drop the live indicator
                # explicitly so the chip can't spin forever
                asyncio.create_task(self.client.send_activity(
                    self.sid, active=False, agent=w.id))
        if self._workers:
            self._push_agents()

    # ---------- persistent interactive channels (channel_* tools) ----------

    _CHAN_NAME = re.compile(r"^[a-z0-9-]{1,16}$")
    _CHAN_MAX = 2

    async def _search_technique(self, query: str, source: str,
                                window: str | None) -> str:
        """Layered technique lookup: vendored refs (always) → kali
        /opt/research grep (offline if provisioned) → site-scoped web
        search (internet-gated). First non-empty leg wins; 'auto' walks
        all three."""
        q = (query or "").strip()[:80]
        src = (source or "auto").strip().lower()
        online = bool(self.ctx.get("session", {}).get("kali_internet"))
        if not q:
            return "error: empty query"
        sites = research.TECHNIQUE_SITES
        if src == "auto":
            legs = ["vendored", "kali", "hacktricks",
                    "payloadsallthethings"]
        elif src == "vendored" or src == "kali" or src in sites:
            legs = [src]
        else:
            return (f"error: unknown source '{src}' — use auto, vendored, "
                    f"kali, or one of {', '.join(sites)}")
        last = f"no technique hits for '{q}'"
        for leg in legs:
            if leg == "vendored":
                r = research.grep_refs(q)
            elif leg == "kali":
                terms = [shlex.quote(t) for t in q.split() if len(t) > 1][:4]
                if not terms:
                    r = "error: query too short for a kali grep"
                    continue
                n = len(terms)
                cmd = (
                    "hits=$(for t in " + " ".join(terms) + "; do "
                    "grep -RilF \"$t\" /opt/research 2>/dev/null; done | "
                    "sort | uniq -c | sort -rn | "
                    f"awk '$1>={n}' | head -6); "
                    "for f in $hits; do echo \"== $f\"; "
                    f"grep -inF -m3 -C1 -- {terms[0]} \"$f\"; done")
                try:
                    res = await self.client.exec_in_kali(
                        self.sid, cmd, window=playbooks.PLAYBOOK_WINDOW)
                    out = (res.get("out") or "").strip()
                except (TimeoutError, httpx.HTTPError) as e:
                    out = ""
                    r = f"error: kali grep failed — {type(e).__name__}"
                else:
                    r = (f"/opt/research hits for '{q}':\n{out[:1600]}"
                         if out else "")
                    if not out:
                        r = (f"no /opt/research hits for '{q}' (kit not "
                             "provisioned? — vendored refs and named "
                             "site sources still work)")
            else:
                if not online:
                    r = ("denied: web — offline lab (kali_internet=false): "
                         "named site sources need the uplink; vendored/kali "
                         "legs work offline")
                else:
                    r = await self._web.search(
                        f"site:{sites[leg]} {q}", 6)
            if r and not r.startswith(("error:", "denied:")):
                last = r
                break
            if r:
                last = r
        asyncio.create_task(self.client.log_action(
            self.sid, "search_technique",
            {"arg": q[:120], "agent": window or "main"},
            {"preview": last[:200],
             "ok": not last.startswith(("error:", "denied:"))}))
        return last

    async def _channel_dispatch(self, t: str, a: dict,
                                window: str | None) -> str:
        """channel_open/send/read/close — named tmux windows (c-<name>)
        for sessions the model converses with turn by turn. Same guards
        as exec: scope check on anything carrying an IP/host, denials
        self-reported via log_denial."""
        name = str(a.get("channel") or "").strip().lower()
        name = name.removeprefix("c-")   # model may pass the window name
        if not self._CHAN_NAME.match(name):
            return ("error: channel name must be [a-z0-9-]{1,16} "
                    "(e.g. c1, ssh1)")
        win = f"c-{name}"
        if t == "channel_open":
            if name in self._channels:
                return (f"error: channel {name!r} already open — "
                        "send/read/close it, or pick another name")
            if len(self._channels) >= self._CHAN_MAX:
                return (f"error: channel limit {self._CHAN_MAX} — "
                        f"open: {sorted(self._channels)}; close one first")
            cmd = str(a.get("command") or a.get("content") or "").strip()
            if not cmd:
                return "error: channel_open needs a command"
            bad = (self._foreign_ip(cmd)
                   or (self._foreign_host(cmd)
                       if self._scope_locked else None))
            if bad:
                return (f"denied: {bad} is outside the authorized scope "
                        "— channels follow the same ROE as exec_in_kali")
            res = await self.client.type_in_pane(self.sid, cmd, window=win)
            if res.get("error"):
                return f"error: channel open failed — {res['error'][:160]}"
            self._channels[name] = {"window": win, "command": cmd[:160],
                                    "opened": time.time()}
            asyncio.create_task(self.client.log_action(
                self.sid, "channel_open",
                {"channel": name, "cmd": cmd[:160]}, {"ok": True}))
            cur = res.get("current_command") or ""
            stale = (f"\nNOTE: window {win} already ran '{cur}' — your "
                     "command was typed INTO that session, not a fresh "
                     "shell (reused pane after restart). channel_close "
                     "and reopen for a clean window."
                     if cur and cur not in ("zsh", "bash", "sh", "fish",
                                            "tmux", str(cmd.split()[0]))
                     else "")
            return (f"channel {name} open on window {win} "
                    f"(running: {cmd[:80]}){stale}\n"
                    f"{str(res.get('out') or '')[-1200:]}")
        if t == "channel_close":
            if name not in self._channels:
                return f"error: channel {name!r} not open"
            # kill-window runs on the main pane — a tmux control call,
            # not a target action
            res = await self.client.exec_in_kali(
                self.sid, f"tmux kill-window -t pentrain-coach:{win}")
            if res.get("error"):
                # keep the registry entry — the window still lives on
                # Kali, so send/read should keep working and a later
                # close can retry
                return (f"error: close failed (main pane busy?) — "
                        f"{res['error'][:120]} — channel {name} kept")
            del self._channels[name]
            asyncio.create_task(self.client.log_action(
                self.sid, "channel_close", {"channel": name}, {"ok": True}))
            return f"channel {name} closed (window {win} killed)"
        # send/read need an open channel
        if name not in self._channels:
            return (f"error: channel {name!r} not open — "
                    f"open: {sorted(self._channels) or 'none'}")
        if t == "channel_read":
            res = await self.client.peek_pane(self.sid, win)
            if res.get("error"):
                return f"error: peek failed — {res['error'][:160]}"
            cur = res.get("current_command") or ""
            return (f"[{name}] {cur or 'idle'}:\n"
                    f"{str(res.get('out') or '')[-1500:]}")
        # channel_send — scope-check the input line too: `ssh root@8.8.8.8`
        # typed INSIDE a channel is still a target connection (pivot!)
        text = str(a.get("text") or a.get("content") or "")
        if not text:
            return "error: channel_send needs text"
        bad = (self._foreign_ip(text)
               or (self._foreign_host(text)
                   if self._scope_locked else None))
        if bad:
            return (f"denied: {bad} outside scope — pivoting out through "
                    "a channel is still out-of-scope")
        res = await self.client.type_in_pane(self.sid, text, window=win)
        if res.get("error"):
            return f"error: send failed — {res['error'][:160]}"
        cur = res.get("current_command") or ""
        return (f"[{name}] {cur or 'idle'}:\n"
                f"{str(res.get('out') or '')[-1500:]}")

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
            if n.get("vulns"):
                bits.append(f"{n['vulns']} vulns")
            # worker-declared coverage + notes merge into the shared pads —
            # the worker's verdict on what it TESTED, not just what output
            # said. Same rows the parent's tools write (dedup by surface).
            n_cov = n_notes = 0
            for row in (parsed.get("coverage") or [])[:12]:
                if isinstance(row, dict) and row.get("surface"):
                    r = self.state.coverage.record(
                        row.get("surface"), row.get("area") or "",
                        row.get("outcome") or "testing",
                        row.get("evidence") or row.get("why") or "",
                        owner=w.id)
                    n_cov += 1 if not r.get("error") else 0
            for row in (parsed.get("notes") or [])[:8]:
                if isinstance(row, dict) and row.get("key"):
                    r = self.state.pad.create(
                        row.get("key"), row.get("text") or "", owner=w.id)
                    n_notes += 1 if not r.get("error") else 0
            if n_cov:
                bits.append(f"{n_cov} coverage")
            if n_notes:
                bits.append(f"{n_notes} notes")
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
        # PTG binding close-out — a bound task settles with the worker:
        # done when it reported, blocked when it died/timeout/killed.
        # The task stays visible (ow kept) so the parent's next plan
        # update sees the attempt's outcome, not a vanished claim.
        if w.task_id and "ptg" not in self._ablate:
            ptg.mark(self.state.plan, w.task_id,
                     "done" if w.status == "done" else "blocked")
        await self.client.send_activity(self.sid, active=False, agent=w.id)
        if w.report:
            meta = self._msg_meta(w.id)
            await self.client.send_chat(
                self.sid, w.report[:2000], kind="action_report", meta=meta)
        # finished-pane cleanup — w-windows pile up across long runs and
        # each holds a shell the model might later mistake for live
        # state; the report already landed in the feed so the scrollback
        # served its purpose
        asyncio.create_task(self.client.exec_in_kali(
            self.sid,
            f"tmux kill-window -t pentrain-coach:{w.id} 2>/dev/null; true"))
        # notify the parent on its guaranteed-read channel — findings are
        # already merged into FACTS, this note announces the finish and
        # points at collect_agent for the full text (s1: three workers
        # finished and died unnoticed, the parent never polled)
        head = next((ln.strip() for ln in (w.report or "").splitlines()
                     if ln.strip()), "")[:110]
        self._worker_done.append(
            f"{w.id} {w.status} — {w.actions} actions in "
            f"{int(time.monotonic() - w.started)}s — task: "
            f"\"{w.task[:80]}\"{f' — {head}' if head else ''} — "
            f"its findings already merged into FACTS; "
            f"collect_agent(\"{w.id}\") returns the full report")
        self._worker_done = self._worker_done[-4:]
        self._worker_reasoning.pop(w.id, None)
        self._push_agents()

    async def _worker_loop(self, w: _Worker) -> None:
        """One worker's act→observe→act loop — private message list (never
        touches _history: interleaved tool pairs would corrupt the parent's
        call/result pairing), shared guards/budgets via _dispatch(window)."""
        cc = self.cfg.get("coach", {})
        turn_cap = int(cc.get("worker_turn_cap", 80))
        time_cap = int(cc.get("worker_time_cap_s", 3600))
        _cov_off = "coverage" in self._ablate
        shared = "\n".join(
            t for t in (
                ("THREAT_MODEL: attacker="
                 + str(self.state.threat_model.get("attacker") or "?")
                 + " | boundaries="
                 + str(self.state.threat_model.get("boundaries") or "?")
                 + " | assets="
                 + str(self.state.threat_model.get("assets") or "?")
                 if self.state.threat_model else ""),
                "" if _cov_off else self.state.coverage.render(300),
                "" if _cov_off else self.state.pad.render(300)) if t)
        msgs = [{"role": "system",
                 "content": render_worker_prompt(
                     self.ctx, w, self.facts.render(500, compact=True),
                     plan_render(self.state.plan, cap=350,
                                 title="OPERATOR_PLAN"),
                     shared_txt=shared,
                     turn_cap=turn_cap, time_cap_s=time_cap)},
                {"role": "user", "content": w.task}]
        t0 = time.monotonic()
        last_out = ""
        try:
            llm_fails = 0
            invalid_turns = 0
            while (w.turns < turn_cap
                   and time.monotonic() - t0 < time_cap):
                # soft wrap-up: a worker that is about to hit its hard caps
                # gets ONE explicit "report now" turn so findings leave as a
                # structured report instead of a timeout output-tail
                turns_left = turn_cap - w.turns
                time_left = time_cap - (time.monotonic() - t0)
                if (not w.wrap_nudged
                        and (turns_left <= 5 or time_left <= 180)):
                    w.wrap_nudged = True
                    msgs.append({
                        "role": "user",
                        "content": (f"BUDGET LOW — {turns_left} turns / "
                                    f"{int(time_left)}s left. STOP new work "
                                    "NOW and emit your report JSON with "
                                    "everything found so far.")})
                try:
                    resp = await self.llm.chat(
                        msgs, tools=worker_tools(w.role),
                        reasoning_effort=self.cfg.get("coach", {}).get(
                            "effort_worker") or "medium")
                except Exception as e:
                    # transient endpoint hiccup (ReadTimeout str() is empty —
                    # log the type). Backoff retries before the worker
                    # legitimately fails into the outer handler — s1-eval:
                    # a single ReadTimeout killed w2 after ~3 turns and the
                    # crash-report lost its in-flight findings context
                    llm_fails += 1
                    await log.awarning("worker llm call failed",
                                       session=self.sid, worker=w.id,
                                       attempt=llm_fails,
                                       error_type=type(e).__name__,
                                       error=str(e) or repr(e))
                    if llm_fails >= 3:
                        raise
                    # short exponential gap (0.05s/0.1s): the timeout itself
                    # already burned real wall time, so the retry only needs
                    # a small spacing — and the worker must settle fast
                    # enough for its time cap to still mean something
                    await asyncio.sleep(0.05 * (2 ** (llm_fails - 1)))
                    continue                               # usually already burned time
                llm_fails = 0
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
                        # include a sample of the unparseable output — bare
                        # "no valid actions parsed" notes leave post-hoc
                        # debugging blind to what the model actually emitted
                        sample = (resp.get("content") or "")[:140].strip()
                        note_txt = (f"[{w.id}] {a['reason']}"
                                    + (f" — raw: {sample!r}" if sample else "")
                                    )[:300]
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
                    w.last_out = last_out
                # per-turn roster push — the chip's action count stays live
                # instead of freezing at its spawn-time snapshot
                self._push_agents()
                if not calls or not exec_acts:
                    # distinguish "finished reporting" from "emitted nothing
                    # usable" — a parse failure or an illegal-tool turn must
                    # not kill the worker after one bad response (s1: w1/w2/w3
                    # each died on their FIRST turn to a parse fail after
                    # ~10min of LLM time, never retried, never collected)
                    none_reason = next(
                        (str(a.get("reason") or "")
                         for a in resp["actions"]
                         if a.get("type") == "none"), "")
                    bad_tools = [str(a.get("type")) for a in resp["actions"]
                                 if a.get("type") not in WORKER_TOOL_NAMES
                                 and a.get("type") != "none"]
                    is_invalid = (bool(bad_tools) or "parsed" in none_reason
                                  or "think block" in none_reason)
                    if is_invalid and invalid_turns < 3:
                        invalid_turns += 1
                        # pair any dispatched tool calls BEFORE the corrective
                        # — an unpaired tool_call corrupts the message list on
                        # strict endpoints
                        if calls:
                            msgs.append({"role": "assistant",
                                         "content": (resp.get("content")
                                                    or None),
                                         "tool_calls": calls})
                            for i, call in enumerate(calls):
                                cid = call.get("id") or f"call_{i}"
                                msgs.append({"role": "tool",
                                             "tool_call_id": cid,
                                             "content": call_results.get(
                                                 cid, "error: dropped")[:2000]})
                        why = (f"invalid tool(s) {bad_tools} — workers only "
                               f"have {sorted(WORKER_TOOL_NAMES)}"
                               if bad_tools else "no tool call parsed")
                        msgs.append({"role": "user", "content": (
                            f"[corrective {invalid_turns}/3] {why} — emit "
                            "exec_in_kali/type_in_pane/wait calls, or your "
                            "final report as plain text.")})
                        continue
                    # no tool calls or only 'none' — the worker is done; its
                    # trailing message IS the report to the parent. UNLESS
                    # the correctives ran out on a parse-broken worker —
                    # then its trailing text is garbage, not a report:
                    # mark failed and take the salvage path so partial
                    # evidence still merges instead of lying 'done'.
                    if is_invalid:
                        w.status = "failed"
                        w.report = (f"worker never produced a valid "
                                    f"report after {invalid_turns} "
                                    f"corrective turns — last output:\n"
                                    f"{last_out[-800:]}")
                    else:
                        w.report = ((resp.get("content") or "").strip()
                                    or last_out[-1500:]
                                    or "(finished silently)")
                        w.status = "done"
                    # a failed report-post must not flip a finished worker
                    # to 'failed' and overwrite its real report
                    with contextlib.suppress(Exception):
                        await self._finish_worker(w)
                    return
                invalid_turns = 0
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
                # bounded ctx — keep the system prompt AND the task brief or
                # the worker drifts off-task after ~15 turns (msgs[:1] alone
                # dropped msgs[1], the whole assignment)
                msgs = msgs[:2] + msgs[-28:]
            w.status = "timeout"
            w.report = (f"hit worker caps after {w.actions} actions/"
                        f"{w.turns} turns — {last_out[-800:]}")
            with contextlib.suppress(Exception):
                await self._finish_worker(w)
        except asyncio.CancelledError:
            w.status = "killed"
            # a killed worker's last output still holds findings — fold its
            # tail into the report so _finish_worker merges it into FACTS
            # rather than letting partial evidence die with the slot
            if not w.report and w.last_out:
                w.report = (f"killed after {w.actions} actions/"
                            f"{w.turns} turns — last output:\n"
                            f"{w.last_out[-400:]}")
            with contextlib.suppress(Exception):
                await self._finish_worker(w)
            raise
        except Exception as e:
            # bare exceptions (httpx.ReadTimeout, asyncio.TimeoutError) have
            # an empty str() — type+repr+traceback are the only usable signal
            kind = type(e).__name__
            detail = str(e) or repr(e)
            w.status = "failed"
            w.report = (f"worker crashed: {kind}: {detail}"
                        + (f"\nlast output: {last_out[-600:]}"
                           if last_out else ""))
            await log.awarning("worker failed", session=self.sid,
                               worker=w.id, error_type=kind,
                               error=detail[:400], exc_info=True)
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
