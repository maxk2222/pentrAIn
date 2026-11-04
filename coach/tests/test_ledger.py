"""Coverage ledger + shared notes pad — dedup, outcome discipline,
bounding, replay semantics, and the worker-report merge path."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach import facts as facts_mod
from coach.ledger import (MAX_SURFACES, CoverageLedger, NotesPad,
                          surface_key)
from coach.percept import parse_worker_report


def test_surface_key_canonicalizes():
    assert surface_key("http://10.0.0.5:80/") == "10.0.0.5:80"
    assert surface_key("  10.0.0.5:80  ") == "10.0.0.5:80"
    assert surface_key("10.0.0.5") == "10.0.0.5"
    assert surface_key("web01 | smb | user") == "web01 | smb | user"


def test_record_dedupes_and_upgrades():
    led = CoverageLedger()
    r = led.record("10.0.0.5:80", "web", "testing")
    assert r["ok"] == "recorded" and r["surface"] == "10.0.0.5:80"
    r = led.record("http://10.0.0.5:80/", "web", "open_gap",
                   "time-based only")
    assert r["ok"] == "updated"
    row = led.get("10.0.0.5:80")
    assert row["outcome"] == "open_gap" and row["area"] == "web"
    assert len(led.rows) == 1


def test_update_requires_existing_row():
    led = CoverageLedger()
    assert "error" in led.update("10.0.0.9:22", "confirmed")
    led.record("10.0.0.9:22", "svc", "testing")
    assert led.update("10.0.0.9:22", "confirmed", "uid=0")["ok"] == "updated"


def test_outcome_alias_and_reject():
    led = CoverageLedger()
    led.record("h:1", "", "ruled_out")
    assert led.get("h:1")["outcome"] == "tested_clean"
    assert "error" in led.record("h:2", "", "moved_on")


def test_eviction_prefers_untested_over_confirmed():
    led = CoverageLedger()
    led.record("confirmed:1", "", "confirmed", "proof")
    for i in range(MAX_SURFACES):
        led.record(f"u:{i}", "", "untested")
    # at capacity — a new confirmed row evicts the oldest untested first
    led.record("confirmed:2", "", "confirmed")
    assert len(led.rows) <= MAX_SURFACES
    assert led.get("confirmed:1") is not None
    assert led.get("confirmed:2") is not None


def test_replay_apply_order():
    led = CoverageLedger()
    log = [
        {"tool": "record_coverage",
         "args": {"surface": "a:1", "outcome": "testing"}},
        {"tool": "update_coverage",
         "args": {"surface": "a:1", "outcome": "confirmed"}},
    ]
    for row in log:
        led.apply(row["tool"], row["args"])
    assert led.get("a:1")["outcome"] == "confirmed"


def test_render_prioritizes_unresolved():
    led = CoverageLedger()
    led.record("z:1", "", "tested_clean")
    led.record("a:2", "", "needs_follow_up", "blocked by WAF")
    out = led.render(500)
    assert out.startswith("COVERAGE:")
    assert out.index("a:2") < out.index("z:1")


def test_notes_pad():
    pad = NotesPad()
    assert pad.create("", "x")["error"]
    pad.create("web01-creds", "admin/adminworks", owner="w1")
    assert pad.create("web01-creds", "admin/secret", owner="main")["ok"] \
        == "updated"
    assert pad.notes["web01-creds"]["text"] == "admin/secret"
    out = pad.render(400)
    assert "SHARED_NOTES" in out and "web01-creds" in out


def test_report_merge_extends_contract():
    """Worker report carrying coverage/notes/vulns parses through the
    extended contract and merges into FactsDB.vulns."""
    report = ('{"summary":"done","coverage":[{"surface":"10.0.0.5:80",'
              '"outcome":"confirmed","evidence":"uid=0"}],'
              '"notes":[{"key":"creds","text":"admin/x works on 80"}],'
              '"vulns":[{"title":"rce via upload","sev":"high",'
              '"host":"10.0.0.5","status":"confirmed",'
              '"evidence":"id; uid=0"}],"next":"pivot"}')
    parsed = parse_worker_report(report)
    assert parsed and parsed["coverage"][0]["outcome"] == "confirmed"
    f = facts_mod.FactsDB()
    n = f.apply_worker_report("w1", parsed)
    assert n["vulns"] == 1
    assert f.vulns[0]["title"] == "rce via upload"
    # re-report dedupes on title+host
    f.apply_worker_report("w2", parsed)
    assert len(f.vulns) == 1
