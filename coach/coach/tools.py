"""Native tool-calling contract for the coach LLM — the single source of truth
for coach actions. tool_calls are normalized into the same action dicts the
JSON-mode contract produced, so dispatch/tests stay unchanged.
"""
from __future__ import annotations

import json

import structlog

from . import playbooks

log = structlog.get_logger(__name__)

# ---------- tool schema (single source of truth) ----------

def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props,
                       "required": required}}}


_str = lambda d: {"type": "string", "description": d}

TOOLS: list[dict] = [
    _fn("send_chat", "Send a markdown message to the trainee chat.",
        {"content": _str("markdown text")}, ["content"]),
    _fn("offer_hint", "Offer a hint at a specific escalation level.",
        {"content": _str("hint text"),
         "level": {"type": "integer", "minimum": 1, "maximum": 3}},
        ["content"]),
    _fn("suggest_command",
        "Suggest a shell command the trainee can confirm or reject.",
        {"command": _str("single POSIX shell line"),
         "why": _str("one short reason")}, ["command"]),
    _fn("exec_in_kali",
        "Execute a shell command on the trainee's Kali machine (autonomy 4).",
        {"command": _str("single POSIX shell line")}, ["command"]),
    _fn("type_in_pane",
        "Type one input line into the busy pane (autonomy 4) — for interactive "
        "sessions: ssh/ftp/nc logins, su/sudo password prompts, menus. Types "
        "the literal text + Enter and returns the pane tail. exec_in_kali "
        "bounces while a foreground program holds the pane; use this instead.",
        {"text": _str("literal input line — e.g. a password or remote command")},
        ["text"]),
    _fn("submit_flag",
        "Submit a flag value literally seen in command output (pentrAIn{...}).",
        {"value": _str("flag value")}, ["value"]),
    _fn("check_flag",
        "Ask the server to verify a state/command-kind flag from FLAGS.",
        {"flag_key": _str("flag key")}, ["flag_key"]),
    _fn("mark_checkpoint",
        "Mark a quest checkpoint as reached (id from CHECKPOINTS_OPEN).",
        {"checkpoint_id": _str("checkpoint id")}, ["checkpoint_id"]),
    _fn("capture_screen",
        "Request a fresh screenshot description of the Kali desktop.", {}, []),
    _fn("lookup_guide",
        "Pull a technique recipe module from the knowledge base — module "
        "ids are listed under GUIDES in your prompt (e.g. 'git-leak', "
        "'pivoting'). Call BEFORE attempting a technique you have not done "
        "in this session: the module carries verbatim commands. Costs no "
        "action budget.",
        {"query": _str("module id or topic keyword")}, ["query"]),
    _fn("record_lesson",
        "Persist a session lesson into shared FACTS — one line of distilled "
        "knowledge you learned the hard way (e.g. 'app01 needs the Bearer "
        "token from /portal/config.js', 'web01 python3 exists but no pip'). "
        "Rendered as lessons: to you, all workers, and restored after "
        "restarts. For hard-won session facts — not quest spoilers or "
        "raw output dumps. Costs no action budget.",
        {"text": _str("one distilled lesson, <=140 chars")}, ["text"]),
    _fn("web_search",
        "Search the web (no API key needed) — ONLY when INTERNET is enabled "
        "for this session. Use for CVEs, exploits, error strings, technique "
        "docs, vendor advisories — e.g. 'CVE-2024-4577 exploit', "
        "'linpeas sudo -l output meaning'. Returns top hits with URLs; then "
        "web_fetch the most promising one. Prefer local tools "
        "(nmap/enum/wordlists) for anything reachable inside the lab.",
        {"query": _str("search query — specific terms work best"),
         "max_results": {"type": "integer", "minimum": 1, "maximum": 10}},
        ["query"]),
    _fn("web_fetch",
        "Fetch and read one URL — extracts the main text (docs, blog posts, "
        "advisories, PoC writeups). Private/lab addresses are denied; use "
        "exec_in_kali curl for lab targets instead. Costs no action budget "
        "but pages are capped — fetch the one best hit, don't crawl.",
        {"url": _str("full http(s) URL, e.g. from web_search results")},
        ["url"]),
    _fn("none",
        "Stay silent; attach a private note kept as your working memory.",
        {"reason": _str("short private note")}, ["reason"]),
    _fn("update_plan",
        "Replace your working plan (max 10 steps) — your roadmap across "
        "restarts and context trims, and the task graph workers bind to. "
        "Update on every phase change: mark steps done once proven, keep "
        "exactly one 'doing'. Optional structure per step: id (bind "
        "spawn_agent via task_id), ph (phase: recon|enum|web|creds|"
        "foothold|privesc|pivot|loot|verify|report), deps (ids that must "
        "finish first), dw (done_when). Persisted; bookkeeping only — "
        "costs no action budget.",
        {"items": {"type": "array",
                   "items": {"type": "object",
                             "properties": {
                                 "t": _str("step, <=110 chars"),
                                 "s": {"type": "string",
                                       "enum": ["todo", "doing", "done",
                                                "blocked", "abandoned"]},
                                 "id": _str("short task id, e.g. p2"),
                                 "ph": _str("phase tag"),
                                 "deps": {"type": "array",
                                          "items": {"type": "string"}},
                                 "ow": _str("owner: main|w1..wN"),
                                 "dw": _str("done_when criterion")},
                             "required": ["t"]}}},
        ["items"]),
    _fn("record_coverage",
        "Record the testing outcome of ONE attack surface (a host:port, an "
        "endpoint, a credential-vector) in the coverage ledger — what did "
        "you TEST and what came of it. Outcomes: untested (declared lead), "
        "testing (in progress), tested_clean (tried, no issue found), "
        "open_gap (plausible but unproven — name the missing proof), "
        "confirmed (evidence-backed result), needs_follow_up (blocked — "
        "say by what). Recording keeps the ledger honest; silently moving "
        "on loses coverage state. Costs no action budget.",
        {"surface": _str("canonical surface, e.g. 10.0.0.5:80 or "
                          "web01|smb|user"),
         "area": _str("risk area, e.g. web|smb|creds|privesc|pivot"),
         "outcome": {"type": "string",
                     "enum": ["untested", "testing", "tested_clean",
                              "open_gap", "confirmed", "needs_follow_up"]},
         "evidence": _str("one-line proof/reason, <=200 chars")},
        ["surface", "outcome"]),
    _fn("update_coverage",
        "Move an EXISTING coverage row to its real outcome — same args as "
        "record_coverage, fails when the surface was never recorded. Use "
        "this instead of recording a second row for the same surface.",
        {"surface": _str("surface key from the ledger"),
         "outcome": {"type": "string",
                     "enum": ["untested", "testing", "tested_clean",
                              "open_gap", "confirmed", "needs_follow_up"]},
         "evidence": _str("one-line proof/reason")},
        ["surface", "outcome"]),
    _fn("list_coverage",
        "List coverage-ledger rows, optionally filtered by outcome — check "
        "what is already covered before spending actions.",
        {"outcome": {"type": "string",
                     "enum": ["untested", "testing", "tested_clean",
                              "open_gap", "confirmed", "needs_follow_up"]}},
        []),
    _fn("create_note",
        "Pin one line of durable cross-agent context onto the shared notes "
        "pad — a working credential set, an endpoint inventory, a "
        "rate-limit quirk the next agent needs. Not a finding, not "
        "coverage: the scratchpad every agent (you + workers) reads at "
        "spawn. Same key updates in place. Costs no action budget.",
        {"key": _str("short label, e.g. 'web01-creds', 'lan-endpoints'"),
         "text": _str("one line of distilled context, <=240 chars")},
        ["key", "text"]),
    _fn("list_notes",
        "List the shared notes pad — cross-agent curated context written "
        "by you or merged from worker reports.", {}, []),
    _fn("record_finding",
        "Record or update ONE typed finding — a vulnerability, exposure or "
        "weakness you identified. status=candidate is a suspicion that "
        "still needs proof; status=confirmed requires concrete evidence "
        "(a claim without it auto-demotes); status=rejected marks a ruled-"
        "out lead. Pass 'id' to update an existing row (the validation "
        "flow); without it title+host dedup applies. Findings are what "
        "build_report renders — unrecorded evidence never reaches the "
        "report. Costs no action budget.",
        {"id": _str("existing finding id (v1, v2…) to update"),
         "title": _str("short finding name, e.g. 'SMB guest share readable'"),
         "sev": {"type": "string",
                 "enum": ["info", "low", "medium", "high", "critical"]},
         "status": {"type": "string",
                    "enum": ["candidate", "confirmed", "rejected"]},
         "host": _str("affected host/surface, e.g. 10.0.0.5 or app01:443"),
         "evidence": _str("concrete proof — command/response detail, "
                          "<=200 chars"),
         "next": _str("recommended next step or remediation, <=120 chars")},
        ["title"]),
    _fn("build_report",
        "Assemble the engagement report draft from recorded findings, "
        "coverage ledger and host data — the result is markdown you then "
        "write to the report path (write_file) for report-checking flags. "
        "Confirmed findings lead; candidates and ruled-out items are listed "
        "separately so unproven claims never read as results.",
        {"title": _str("report title, e.g. 'LAN Assessment Report'")},
        []),
    _fn("wait",
        "Wait N seconds without acting — for time-dependent state changes "
        "(cron jobs, service startup, lockout/cooldown timers). Touches "
        "nothing on the pane and costs no action budget. Prefer this over "
        "polling the same check in a loop.",
        {"seconds": {"type": "integer", "minimum": 5, "maximum": 240,
                     "description": "seconds to wait — capped by "
                                    "coach.wait_max_s"},
         "why": _str("what you're waiting for, e.g. 'root cron every 2min'")},
        ["seconds"]),
    _fn("spawn_agent",
        "Delegate an INDEPENDENT subtask to a parallel worker agent running "
        "on its own tmux window (w1..w4) — it executes commands autonomously "
        "and reports findings back via collect_agent. Use for parallel work "
        "(e.g. enumerating different hosts/services at once); do NOT spawn "
        "for sequential steps that depend on each other's results.",
        {"task": _str("self-contained worker task — what to do, the ACCESS "
                      "PATH (host, creds, pivot), and what to report back"),
         "role": {"type": "string",
                  "enum": ["general", "recon", "web", "creds", "svc",
                           "privesc", "pivot", "verify", "ai-audit",
                           "cloud-audit", "exploit-audit", "linux-audit"],
                  "description": "specialist role — narrows the worker's "
                                 "operating contract"},
         "done_when": _str("acceptance criterion the report is measured "
                            "against, e.g. 'ports+versions for all live "
                            "hosts' — <=140 chars"),
         "task_id": _str("plan task id to bind (from update_plan items "
                          "with id) — the worker's finish marks it "
                          "done/blocked; max 3 attempts per task")},
        ["task"]),
    _fn("collect_agent",
        "Read a worker's report — waits up to ~40s if it is still running, "
        "otherwise returns its live status line.",
        {"worker_id": _str("worker id, e.g. w1")}, ["worker_id"]),
    _fn("agent_status",
        "List all workers: id, status, action count, elapsed time, task.", {},
        []),
    _fn("kill_agent",
        "Cancel a running worker before it finishes.",
        {"worker_id": _str("worker id, e.g. w1")}, ["worker_id"]),
    _fn("search_memory",
        "Search long-term attack-path memory — distilled SUCCESSFUL "
        "sequences from past sessions (recon→foothold→privesc chains that "
        "worked). Call at planning time for an unfamiliar target or when "
        "a phase stalls: a hit is a proven sequence to ADAPT, not a "
        "guarantee — verify it fits before following it. Hits carry ids "
        "for play_outcome feedback. Costs no action budget.",
        {"query": _str("situation keywords — services/tech/goal, e.g. "
                       "'wordpress creds foothold' or 'linux privesc'")},
        ["query"]),
    _fn("record_play",
        "Distill ONE successful attack sequence into long-term memory — "
        "call when the quest/engagement completes or a major chain "
        "succeeds: name it, tag the techniques, list the ordered steps "
        "that WORKED. Future sessions retrieve this via search_memory — "
        "write for an agent that never saw this one. Moves, not loot: "
        "never put flags, passwords or session-specific secrets in "
        "steps. Costs no action budget.",
        {"title": _str("one-line chain name, e.g. 'wp-admin creds → "
                       "theme shell → suid root'"),
         "tags": {"type": "array", "items": {"type": "string"},
                  "description": "technique/service tags: wordpress|ssh|"
                                 "sudo|smb …"},
         "steps": {"type": "array", "items": {"type": "string"},
                   "description": "ordered steps that worked, each "
                                  "'phase: what did it' <=140 chars"},
         "outcome": _str("what the chain achieved, <=200 chars")},
        ["title", "tags", "steps"]),
    _fn("play_outcome",
        "Report whether a memory path you followed worked — play_id from "
        "a search_memory hit. ok=true reinforces it for the next session; "
        "ok=false marks a miss so stale paths lose rank.",
        {"play_id": {"type": "integer",
                     "description": "attack-path id from search_memory"},
         "ok": {"type": "boolean"}},
        ["play_id", "ok"]),
    _fn("threat_model",
        "Set or amend the engagement threat-model card — the attacker's "
        "assumed position, the trust boundaries in play, the crown-jewel "
        "assets to reach. Shared with workers at spawn so parallel tasks "
        "aim at what matters; amendable as facts emerge. Engagement "
        "bookkeeping — costs no action budget.",
        {"attacker": _str("assumed attacker position/capability, e.g. "
                          "'external, unauthenticated, standard tools'"),
         "boundaries": _str("trust boundaries crossed, e.g. 'internet→dmz "
                            "web tier→internal lan'"),
         "assets": _str("crown jewels to reach or prove access to")},
        []),
    _fn("run_playbook",
        "Run ONE bounded macro-playbook — a scripted command chain with "
        "built-in scope check, timeout and result parser (facts+coverage "
        "merge automatically). Use for commodity phases instead of "
        "hand-rolling every step: "
        + playbooks.names()
        + ". Args are validated; out-of-scope targets are denied before "
        "anything runs. The result returns coverage rows merged plus an "
        "output tail.",
        {"name": {"type": "string",
                  "enum": [p.name for p in playbooks.PLAYBOOKS]},
         "args": {"type": "object",
                  "description": "playbook args — target (host/ip), port, "
                                 "user, creds etc; schema per playbook"}},
        ["name"]),
    _fn("channel_open",
        "Open a persistent interactive channel on its own tmux window "
        "(c1/c2) — for sessions you must converse with turn by turn: "
        "ssh, msfconsole, ftp, nc listeners, remote shells. The command "
        "runs through the same scope/deny guards as exec_in_kali. Max "
        "2 open channels; read/send/close them by name.",
        {"channel": _str("channel name, e.g. c1 — becomes tmux window c-c1"),
         "command": _str("command that STARTS the interactive session")},
        ["channel", "command"]),
    _fn("channel_send",
        "Type one input line into an open channel — passwords, remote "
        "shell commands, menu choices. Returns the pane tail.",
        {"channel": _str("open channel name"),
         "text": _str("literal input line")},
        ["channel", "text"]),
    _fn("channel_read",
        "Read an open channel's pane tail without typing — check what a "
        "long-running listener or slow session produced.",
        {"channel": _str("open channel name")}, ["channel"]),
    _fn("channel_close",
        "Close an open channel — kills its tmux window and frees the "
        "slot. Always close channels you no longer need.",
        {"channel": _str("open channel name")}, ["channel"]),
]

# tools a spawned worker may call — exec + research only: no chat, flags,
# checkpoints or nested spawns; completion stays with the parent coach.
WORKER_TOOL_NAMES = {"exec_in_kali", "type_in_pane", "wait", "none",
                     "update_plan", "lookup_guide", "record_lesson",
                     "web_search", "web_fetch"}
SUBAGENT_TOOL_NAMES = {"spawn_agent", "collect_agent", "agent_status",
                       "kill_agent"}

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}

# which tools may be *offered* at which autonomy level — don't let the model
# pick an action the gate will refuse anyway, and on takeover don't offer
# suggest_command at all (its confirm-chip can never be clicked in auto mode)
_LEVEL_TOOLS = {
    1: {"send_chat", "offer_hint", "capture_screen", "update_plan",
        "lookup_guide", "record_lesson", "none"},
    2: {"send_chat", "offer_hint", "mark_checkpoint", "capture_screen",
        "update_plan", "lookup_guide", "record_lesson", "none"},
    3: {"send_chat", "offer_hint", "suggest_command", "mark_checkpoint",
        "capture_screen", "update_plan", "lookup_guide", "record_lesson",
        "web_search", "web_fetch", "none"},
    4: {"send_chat", "offer_hint", "exec_in_kali", "type_in_pane",
        "submit_flag", "check_flag", "mark_checkpoint", "capture_screen",
        "wait", "update_plan", "lookup_guide", "record_lesson",
        "web_search", "web_fetch", "none",
        "record_coverage", "update_coverage", "list_coverage",
        "create_note", "list_notes", "record_finding", "build_report",
        "search_memory", "record_play", "play_outcome", "threat_model",
        "run_playbook",
        "channel_open", "channel_send", "channel_read", "channel_close"},
}


def tools_for_level(level: int, *, subagents: bool = False) -> list[dict]:
    allowed = set(_LEVEL_TOOLS.get(level, _LEVEL_TOOLS[1]))
    if level >= 4 and subagents:
        allowed |= SUBAGENT_TOOL_NAMES
    return [t for t in TOOLS if t["function"]["name"] in allowed]


def worker_tools(role: str | None = None) -> list[dict]:
    # role-gated subsets — verify workers reproduce evidence read-only, so
    # they get no update_plan (no roadmap to maintain) and no record_lesson
    # (they report into the merge instead of curating shared memory)
    drop = {"verify": {"update_plan", "record_lesson"}}.get(role or "", set())
    return [t for t in TOOLS
            if t["function"]["name"] in WORKER_TOOL_NAMES - drop]


WORKER_ROLES = {"general", "recon", "web", "creds", "svc", "privesc",
                "pivot", "verify", "ai-audit", "cloud-audit",
                "exploit-audit", "linux-audit"}


# ---------- normalization ----------

def call_to_action(call: dict) -> dict | None:
    """One OpenAI tool_call → action dict, or None when unusable."""
    fn = call.get("function") or {}
    name = fn.get("name")
    if name not in TOOL_NAMES:
        return None
    raw = fn.get("arguments") or "{}"
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(args, dict):
            return None
    except (json.JSONDecodeError, TypeError):
        return None
    action = {"type": name, **args}
    if call.get("id"):
        action["_call_id"] = call["id"]   # pairing key for the tool reply
    return action


def calls_to_actions(message: dict) -> list[dict]:
    """Normalize a response message into ordered action dicts.

    - content + tool_calls → send_chat action first (narration before work)
    - content only → [{"type":"send_chat", ...}]
    - empty + no calls → [{"type":"none"}]
    """
    actions: list[dict] = []
    content = (message.get("content") or "").strip()
    calls = message.get("tool_calls") or []
    if content and calls:
        actions.append({"type": "send_chat", "content": content[:2000]})
    for call in calls:
        a = call_to_action(call)
        if a is not None:
            actions.append(a)
        else:
            log.warning("dropping unusable tool_call",
                        name=(call.get("function") or {}).get("name"))
    if actions:
        return actions
    if content:
        return [{"type": "send_chat", "content": content[:2000]}]
    return [{"type": "none"}]


# ---------- history shaping ----------

def wire_history(msgs: list[dict], tools_active: bool) -> list[dict]:
    """History as sent on the wire. With tools inactive, `tool` messages and
    `assistant.tool_calls` must not reach a non-tools request (some templates
    reject tool roles there) — chat content stays, results live on via the
    persisted action_report messages."""
    if tools_active:
        out = list(msgs)
    else:
        out = []
        for m in msgs:
            if m.get("role") == "tool":
                continue
            m = dict(m)
            m.pop("tool_calls", None)
            out.append(m)
    # template compat: several chat templates (LM Studio llama.cpp jinja,
    # some MLX builds) require the FIRST non-system message to be a user
    # turn — a seeded assistant welcome at index 0 makes them 400 with
    # "No user query found". Leading assistant/tool entries are pure
    # context loss, never a pairing violation.
    while out and out[0].get("role") in ("assistant", "tool"):
        out.pop(0)
    return out


def trim_history(msgs: list[dict], cap: int) -> list[dict]:
    """Apply HISTORY_CAP without leaving orphan `tool` messages: a tool reply
    without its assistant.tool_calls parent breaks strict templates."""
    msgs = list(msgs)[-cap:] if cap else list(msgs)
    while msgs and msgs[0].get("role") == "tool":
        msgs.pop(0)
    return msgs
