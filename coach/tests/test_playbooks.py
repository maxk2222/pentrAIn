"""Playbook macros — build/parse correctness, arg/tool/scope gating,
and the coverage+notes merge into shared bookkeeping."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach import playbooks
from coach.loop import SessionCoach


class FakeClient:
    def __init__(self, out="", scope=None, tools="nmap curl gobuster "
                                                 "smbclient sshpass john "
                                                 "proxychains"):
        self.out = out
        self.ctx = {
            "session": {"id": 1, "state": "active", "autonomy_level": 4,
                        "coach_enabled": True, "subagents_enabled": True},
            "session_tools": tools,
            "quest": {"title": "Lab", "track": "net", "tier": 1,
                      "briefing": "b", "coach_context": "", "checkpoints": [],
                      "escalation": {},
                      "targets": [{"name": "app01", "ip": "10.1.10.21"}]},
            "flags": [], "checkpoints_hit": [], "telemetry_tail": [],
            "messages": [], "exec_count": 0,
            "profile": {"track_levels": {"net": 1}},
        }
        if scope is not None:
            self.ctx["scope"] = scope

    async def send_chat(self, *a, **k): return {}
    async def session_context(self, sid): return self.ctx
    async def log_action(self, *a, **k): return {}
    async def log_denial(self, *a, **k): return {}
    async def stream_draft(self, *a, **k): pass
    async def send_activity(self, *a, **k): pass
    async def send_agents(self, *a, **k): pass
    async def exec_in_kali(self, sid, cmd, window=None):
        self.last_cmd, self.last_window = cmd, window
        return {"out": self.out, "exitcode": 0, "visible": True}
    async def report_llm_usage(self, *a, **k): return {}


class FakeLlm:
    model = "fake"

    async def chat(self, *a, **k):
        return {"content": "", "actions": [{"type": "none"}],
                "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}


async def _coach(client=None):
    c = client or FakeClient()
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    return coach


# ---------- spec-level ----------

def test_all_playbooks_build_single_line():
    for pb in playbooks.PLAYBOOKS:
        args = {"target": "10.0.0.5", "port": "80", "user": "u",
                "pass": "p w", "hash": "abc123", "path": "/etc/passwd",
                "via": "10.0.0.9", "service": "ssh", "proto": "ssh",
                "share": "c$"}
        cmd = pb.build({k: v for k, v in args.items()
                        if k in pb.required + pb.optional})
        assert isinstance(cmd, str) and "\n" not in cmd
        assert cmd.strip()


def test_nmap_parse_extracts_ports_and_note():
    out = ("22/tcp   open  ssh     OpenSSH 8.9\n"
           "80/tcp   open  http    Apache httpd 2.4\n"
           "Nmap done: 1 IP address (10.0.0.5) up")
    res = playbooks.get("full_recon").parse(out)
    surfaces = {c["surface"] for c in res["coverage"]}
    assert "10.0.0.5:22" in surfaces and "10.0.0.5:80" in surfaces
    assert res["notes"] and "22/ssh" in res["notes"][0]["text"]


def test_web_parse_paths_and_root():
    out = ("ROOT 200 4321b\n/.git (Status: 200)\n/admin (Status: 403)\n"
           "/gone (Status: 404)\n")
    res = playbooks.get("web_enum").parse(out)
    surfaces = {c["surface"] for c in res["coverage"]}
    assert "web:/" in surfaces and "web:/.git" in surfaces
    assert "web:/gone" not in surfaces          # 404 isn't a surface
    assert res["notes"][0]["key"] == "web-endpoints"


def test_cred_try_parse_success_vs_fail():
    pb = playbooks.get("cred_try")
    ok = pb.parse("uid=33(www-data) gid=33(www-data)\nweb01")
    bad = pb.parse("Permission denied, please try again.")
    assert "SUCCEEDED" in ok["notes"][0]["text"]
    assert "failed" in bad["notes"][0]["text"]


# ---------- dispatch gating ----------

async def test_run_playbook_happy_path_merges_coverage():
    c = FakeClient(out="22/tcp open ssh OpenSSH\n80/tcp open http Apache\n"
                       "Nmap done: 1 IP (10.1.10.21)")
    coach = await _coach(c)
    _v, r = await coach._dispatch(
        {"type": "run_playbook",
         "name": "full_recon", "args": {"target": "10.1.10.21"}})
    assert r.startswith("playbook full_recon done")
    assert c.last_window == playbooks.PLAYBOOK_WINDOW     # dedicated pane
    surfaces = {row["surface"] for row in coach.state.coverage.rows.values()}
    assert "10.1.10.21:22" in surfaces
    await coach.stop()


async def test_run_playbook_missing_args():
    coach = await _coach()
    _v, r = await coach._dispatch(
        {"type": "run_playbook", "name": "full_recon", "args": {}})
    assert r.startswith("error:") and "target" in r
    await coach.stop()


async def test_run_playbook_missing_tool():
    c = FakeClient(tools="nmap curl")          # no gobuster
    coach = await _coach(c)
    _v, r = await coach._dispatch(
        {"type": "run_playbook",
         "name": "web_enum", "args": {"target": "10.1.10.21"}})
    assert r.startswith("error:") and "gobuster" in r
    await coach.stop()


async def test_run_playbook_scope_denied():
    scope = {"locked": True, "authorized_by": "op",
             "nets": ["203.0.113.0/29"], "hosts": [], "ports": []}
    c = FakeClient(scope=scope)
    coach = await _coach(c)
    _v, r = await coach._dispatch(
        {"type": "run_playbook",
         "name": "full_recon", "args": {"target": "198.51.100.9"}})
    assert r.startswith("denied:")
    assert not getattr(c, "last_cmd", None)     # nothing was typed
    await coach.stop()


async def test_run_playbook_in_scope_runs():
    scope = {"locked": True, "authorized_by": "op",
             "nets": ["203.0.113.0/29"], "hosts": [], "ports": []}
    c = FakeClient(scope=scope, out="80/tcp open http")
    coach = await _coach(c)
    _v, r = await coach._dispatch(
        {"type": "run_playbook",
         "name": "full_recon", "args": {"target": "203.0.113.3"}})
    assert r.startswith("playbook full_recon done")
    await coach.stop()


async def test_run_playbook_unknown_name():
    coach = await _coach()
    _v, r = await coach._dispatch(
        {"type": "run_playbook", "name": "nope", "args": {}})
    assert r.startswith("error: unknown playbook")
    assert "full_recon" in r                      # error teaches the names
    await coach.stop()


def test_tool_enum_matches_registry():
    """The schema enum must equal the playbook registry — a stale literal
    here sends the model after names that don't exist."""
    from coach import tools as toolmod
    spec = next(t for t in toolmod.TOOLS
                if t["function"]["name"] == "run_playbook")
    enum = spec["function"]["parameters"]["properties"]["name"]["enum"]
    assert set(enum) == {p.name for p in playbooks.PLAYBOOKS}


async def test_run_playbook_bad_port_no_crash():
    """A non-numeric port arg is a model error — the turn survives."""
    coach = await _coach()
    _v, r = await coach._dispatch(
        {"type": "run_playbook",
         "name": "vuln_triage",
         "args": {"target": "10.1.10.21", "port": "eighty"}})
    assert r.startswith("error:") and "port" in r.lower()
    await coach.stop()


async def test_run_playbook_args_not_dict():
    coach = await _coach()
    _v, r = await coach._dispatch(
        {"type": "run_playbook",
         "name": "full_recon", "args": ["10.1.10.21"]})
    assert r.startswith("error:")
    await coach.stop()


async def test_loot_pull_path_metachars_rejected():
    coach = await _coach()
    _v, r = await coach._dispatch(
        {"type": "run_playbook", "name": "loot_pull",
         "args": {"target": "10.1.10.21", "user": "u", "pass": "p",
                  "proto": "smb",
                  "path": "x'; touch /tmp/pwned; '"}})
    assert r.startswith("error:")
    await coach.stop()


def test_pivot_tunnel_outlives_the_command():
    """The SOCKS tunnel must survive past the scan — a bound tighter
    than the scan's own timeout strands the pivot immediately."""
    cmd = playbooks.get("pivot_setup").build(
        {"via": "10.0.0.9", "target": "10.0.0.5",
         "user": "u", "pass": "p"})
    tunnel = next(s for s in cmd.split(";")
                  if "-D 1080" in s and "sshpass" in s)
    assert "timeout 900" in tunnel          # > the 60s scan bound
