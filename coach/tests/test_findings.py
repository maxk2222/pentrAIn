"""Typed findings — record_finding semantics (create/update/dedup/demote),
the build_report draft, and restart replay of the finding log."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.facts import FactsDB
from coach.loop import SessionCoach


class FakeClient:
    def __init__(self):
        self.logged = []
        self.ctx = {
            "session": {"id": 1, "state": "active", "autonomy_level": 4,
                        "coach_enabled": True, "subagents_enabled": True},
            "quest": {"title": "Q", "track": "net", "tier": 1,
                      "briefing": "b", "coach_context": "", "checkpoints": [],
                      "escalation": {}, "targets": []},
            "flags": [], "checkpoints_hit": [], "telemetry_tail": [],
            "messages": [], "exec_count": 0,
            "profile": {"track_levels": {"net": 1}},
            "scope": {"locked": True, "nets": ["203.0.113.0/29"],
                      "hosts": ["app.example.com"], "ports": [443],
                      "authorized_by": "op"},
        }

    async def send_chat(self, *a, **k): return {}
    async def session_context(self, sid): return self.ctx
    async def log_action(self, sid, tool, args, result):
        self.logged.append({"tool": tool, "args": args, "result": result})
    async def stream_draft(self, *a, **k): pass
    async def send_activity(self, *a, **k): pass
    async def send_agents(self, *a, **k): pass
    async def exec_in_kali(self, *a, **k):
        return {"out": "ok", "exitcode": 0, "visible": True}
    async def report_llm_usage(self, *a, **k): return {}


class FakeLlm:
    model = "fake"

    async def chat(self, *a, **k):
        return {"content": "", "actions": [{"type": "none"}],
                "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}


async def _coach():
    c = FakeClient()
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    return coach, c


# ---------- FactsDB unit semantics ----------

def test_finding_create_dedup_and_ids():
    f = FactsDB()
    r1 = f.apply_finding({"title": "SMB guest share", "host": "10.0.0.5",
                          "sev": "medium"})
    assert r1["id"] == "v1" and r1["status"] == "candidate"
    # same title+host → update in place, no new id
    r2 = f.apply_finding({"title": "SMB guest share", "host": "10.0.0.5",
                          "evidence": "anon read of //10.0.0.5/public"})
    assert r2 is r1 and r2["id"] == "v1" and len(f.vulns) == 1
    r3 = f.apply_finding({"title": "default creds", "host": "10.0.0.6"})
    assert r3["id"] == "v2"


def test_confirmed_requires_evidence():
    f = FactsDB()
    r = f.apply_finding({"title": "RCE", "host": "h", "status": "confirmed"})
    assert r["status"] == "candidate"          # claim without proof demotes
    r = f.apply_finding({"title": "RCE", "host": "h", "status": "confirmed",
                         "evidence": "uid=0(root) from reverse shell"})
    assert r["status"] == "confirmed"


def test_finding_update_by_id():
    f = FactsDB()
    r1 = f.apply_finding({"title": "weak tls", "host": "h:443"})
    r = f.apply_finding({"id": r1["id"], "status": "rejected",
                         "evidence": "TLS1.2 only — no vulnerable ciphers"})
    assert r["status"] == "rejected"
    assert f.apply_finding({"id": "v99", "title": "x"}) is None


def test_worker_vulns_merge_through_same_path():
    f = FactsDB()
    counts = f.apply_worker_report("w1", {
        "vulns": [{"title": "anon ftp", "host": "10.0.0.7", "sev": "low",
                   "status": "confirmed",
                   "evidence": "230 Login successful (anonymous)"}]})
    assert counts["vulns"] == 1
    assert f.vulns[0]["id"] == "v1" and f.vulns[0]["owner"] == "w1"


# ---------- dispatch + report + replay ----------

async def test_record_finding_dispatch_and_log():
    coach, c = await _coach()
    _v, r = await coach._dispatch({"type": "record_finding",
                                 "title": "weak tls ciphers",
                                 "host": "app.example.com:443",
                                 "sev": "medium"})
    assert r.startswith("finding v1")
    await asyncio.sleep(0)   # log_action task
    assert any(x["tool"] == "record_finding" for x in c.logged)
    # update by id
    _v, r = await coach._dispatch({"type": "record_finding", "id": "v1",
                                 "status": "confirmed",
                                 "evidence": "sslscan: TLS_RSA_WITH_RC4 accepted"})
    assert "confirmed" in r
    await coach.stop()


async def test_build_report_groups_by_status():
    coach, _c = await _coach()
    f = coach.facts
    f.apply_finding({"title": "SMB guest", "host": "203.0.113.3",
                     "sev": "high", "status": "confirmed",
                     "evidence": "anonymous IPC$ read"})
    f.apply_finding({"title": "possible sqli", "host": "app.example.com",
                     "evidence": "time-based probe pending"})
    _v, r = await coach._dispatch({"type": "build_report"})
    assert "# Penetration Test Report" in r
    assert "Authorized scope" in r and "203.0.113.0/29" in r
    assert "### [v1] SMB guest" in r
    assert "Candidates (unvalidated)" in r and "possible sqli" in r
    assert "write_file" in r.lower() or "report path" in r
    await coach.stop()


async def test_findings_replay_on_restart():
    """record_finding rows replay from ctx['ledger_log'] like coverage —
    a coach restart keeps the finding set + stable ids."""
    c = FakeClient()
    c.ctx["ledger_log"] = [
        {"tool": "record_finding",
         "args": {"title": "SMB guest", "host": "10.0.0.5", "sev": "high",
                  "status": "confirmed",
                  "evidence": "anonymous share listing", "agent": "main"}},
        {"tool": "record_finding",
         "args": {"id": "v1", "status": "rejected"}},
    ]
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    assert len(coach.facts.vulns) == 1
    v = coach.facts.vulns[0]
    assert v["id"] == "v1" and v["status"] == "rejected"
    await coach.stop()
