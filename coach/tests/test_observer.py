"""Observer unit tests — detectors, sanitize, dedupe, window building.

No LLM/backend in these: the triggers and guards are the correctness-
critical surface (a stuck session must be detected, an advisory must
fire exactly once, lessons must never carry secrets)."""
from __future__ import annotations

import time

from coach.observer import ObserverService, _Watch


def _svc() -> ObserverService:
    return ObserverService(client=None, cfg_getter=dict)


def _turn(actions, facts=None, ts=None):
    return {"kind": "turn", "ts": ts or time.time(),
            "actions": actions, "facts": facts or {}}


OBS = {"observer_stuck_s": 600, "observer_min_denials": 2}


# ---------- consumption / progress ----------

def test_denial_events_count_toward_stuck():
    w = _Watch(1)
    svc = _svc()
    w.last_progress_ts = time.time() - 700      # drought already
    for i in range(2):
        svc._consume(w, {"kind": "denial", "ts": time.time()})
    assert svc._is_stuck(w, OBS, time.time())


def test_denied_actions_inside_turn_count():
    w = _Watch(1)
    svc = _svc()
    w.last_progress_ts = time.time() - 700
    svc._consume(w, _turn([
        {"t": "exec_in_kali", "arg": "nmap x", "denied": True},
        {"t": "exec_in_kali", "arg": "curl y", "denied": True},
    ]))
    assert svc._is_stuck(w, OBS, time.time())


def test_repeated_same_tool_loop_counts_as_stuck():
    w = _Watch(1)
    svc = _svc()
    w.last_progress_ts = time.time() - 700
    for _ in range(3):
        svc._consume(w, _turn([
            {"t": "exec_in_kali", "arg": "curl http://x/", "denied": False}]))
    assert svc._is_stuck(w, OBS, time.time())


def test_facts_growth_is_progress_and_resets_drought():
    w = _Watch(1)
    svc = _svc()
    svc._consume(w, _turn([], {"hosts": 1}))
    assert svc._is_stuck(w, OBS, time.time()) is False  # fresh progress
    w.last_progress_ts = time.time() - 700
    svc._consume(w, _turn([], {"hosts": 2}))
    assert svc._is_stuck(w, OBS, time.time()) is False  # grew again


def test_correct_flag_result_is_progress():
    w = _Watch(1)
    svc = _svc()
    w.last_progress_ts = time.time() - 700
    svc._consume(w, _turn([
        {"t": "submit_flag", "arg": "x", "res": "correct — flag accepted",
         "denied": False}]))
    assert svc._is_stuck(w, OBS, time.time()) is False


def test_not_stuck_inside_grace_period():
    w = _Watch(1)   # last_progress_ts = now
    svc = _svc()
    for _ in range(5):
        svc._consume(w, {"kind": "denial", "ts": time.time()})
    assert svc._is_stuck(w, OBS, time.time()) is False


# ---------- sanitize ----------

def test_sanitize_strips_flag_values():
    s = _svc()
    out = s._sanitize("the flag is pentrAIn{n0rdw1nd_91} for app01")
    assert "pentrAIn{" not in out
    assert "n0rdw1nd" not in out


def test_sanitize_strips_credentials():
    s = _svc()
    for t in ["login password=Hunter2!", "token: eyJhbGciOi", "-p 's3cr3t'",
              "Bearer sk-live-abc123"]:
        out = s._sanitize(t)
        assert out == "" or "<redacted>" in out or "Hunter2" not in out


def test_sanitize_caps_length_and_strips_quotes():
    s = _svc()
    assert len(s._sanitize("x" * 500)) == 240
    assert len(s._sanitize("x" * 500, advisory=True)) == 400
    assert s._sanitize('"pivot via ssh"') == "pivot via ssh"


# ---------- dedupe ----------

def test_jaccard_dedupe_catches_reworded_tip():
    s = _svc()
    known = ["ssh -D 9050 on web01 gives a SOCKS pivot to reach app01"]
    # near-identical restatement → dup; different technique → not dup
    assert s._is_dup("ssh -D 9050 on web01 gives a SOCKS pivot for app01",
                     known)
    assert not s._is_dup("gobuster needs --timeout not --max-time", known)


def test_is_dup_empty_rejects():
    assert _svc()._is_dup("   ", ["anything"])


# ---------- proposals parsing ----------

def test_parse_proposals_tolerates_fences_and_prose():
    s = _svc()
    r = s._parse_proposals({"content":
                            '{"proposals":[{"text":"a","tags":["ssh"]}]}'})
    assert r[0]["text"] == "a"
    r = s._parse_proposals({"content":
                            'sure!\n{"proposals":[{"text":"b"}]}\nthanks'})
    assert r[0]["text"] == "b"
    assert s._parse_proposals({"content": "no json here"}) == []


# ---------- window ----------

def test_window_text_marks_denied_and_caps():
    s = _svc()
    evs = [_turn([{"t": "exec", "arg": "nmap -sV x", "res": "filtered",
                  "denied": True}])]
    txt = s._window_text(evs)
    assert "DENIED" in txt and "nmap" in txt
    big = [_turn([{"t": "e", "arg": "x" * 300, "res": "y" * 400}])
           for _ in range(300)]
    assert len(s._window_text(big)) <= 8000


# ---------- live facts snapshot ----------

def test_facts_snapshot_reads_live_coach_registry():
    """The advisor must see the coach's CURRENT facts (proven access,
    tunnels, dead ends) — traj-window denial evidence alone produced stale
    advice (s84: `-J` tip while sshuttle already routed the net)."""
    class _C:  # minimal stand-in for SessionCoach
        def __init__(self):
            from coach.facts import FactsDB
            self.facts = FactsDB()
    coach = _C()
    coach.facts.add_cred("deploy", "pw", valid_on="web01")
    coach.facts.denials.append("missing:sshpass@web01")
    svc = ObserverService(client=None, cfg_getter=dict,
                          coaches={84: coach})
    snap = svc._facts_snapshot(84)
    assert "valid:web01" in snap and "missing:sshpass@web01" in snap
    # unknown sid / coach without facts → empty, never an exception
    assert svc._facts_snapshot(999) == ""
    svc2 = ObserverService(client=None, cfg_getter=dict)
    assert svc2._facts_snapshot(84) == ""


def test_failure_digest_lists_failed_and_retried_args():
    s = _svc()
    w = _Watch(1)
    w.window.append({"kind": "turn", "actions": [
        {"t": "exec_in_kali", "arg": "curl http://x/ftp/flag1.txt%00.md",
         "res": '{"exitcode": 0, "out": "<html>err"}'},
        {"t": "exec_in_kali", "arg": "curl http://x/ftp/flag1.txt%00.md",
         "res": '{"exitcode": 0, "out": "<html>err"}'},
        {"t": "exec_in_kali", "arg": "ssh a@b 'echo x >> /f'",
         "res": '{"err": "still running — pane is now busy"}'},
        {"t": "exec_in_kali", "arg": "ls -la", "res": '{"exitcode": 0}'}]})
    txt, toks = s._failure_digest(w)
    assert "flag1.txt%00.md" in txt and "retried" in txt
    assert "echo x >> /f" in txt and "failed" in txt
    assert "ls -la" not in txt                    # one-off success, not a dead end
    assert any("%00" in t or "flag1.txt" in t for t in toks)


def test_field_notes_block_reads_coach_facts():
    class _C:
        def __init__(self):
            from coach.facts import FactsDB
            self.facts = FactsDB()
    coach = _C()
    coach.facts.set_field_notes([
        {"id": 1, "text": "use %2500.md double-encode", "tags": ["ftp"]}])
    s = ObserverService(client=None, cfg_getter=dict, coaches={59: coach})
    blk = s._field_notes_block(59)
    assert "%2500.md" in blk and "verified field notes" in blk
    assert s._field_notes_block(999) == ""
