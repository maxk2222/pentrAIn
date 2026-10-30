"""Coach policy + state-machine tests (no backend needed)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.policy import Policy
from coach.state import CheckpointMatcher, SessionState


def _st(**kw):
    st = SessionState(session_id=1)
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def test_spectate_never_proactive():
    p = Policy({}, nudge_s=60, hint_s=120)
    st = _st(autonomy_level=1, state="active")
    st.last_progress_ts = time.time() - 9999
    st.last_activity_ts = time.time() - 9999
    d = p.evaluate(st)
    assert not d.may_proactive


def test_inactive_session_never_proactive():
    p = Policy({}, nudge_s=60, hint_s=120)
    st = _st(autonomy_level=3, state="deploying")
    d = p.evaluate(st)
    assert not d.may_proactive


def test_cooldown_blocks_repeat_nudges():
    p = Policy({}, nudge_s=60, hint_s=120)
    st = _st(autonomy_level=3, state="active")
    st.last_progress_ts = time.time() - 5000
    st.last_nudge_ts = time.time() - 10   # nudged 10s ago
    d = p.evaluate(st)
    assert not d.may_proactive
    st.last_nudge_ts = time.time() - 400  # cooldown over
    d = p.evaluate(st)
    assert d.may_proactive


def test_stuck_escalates_urgency():
    p = Policy({"nudge_after_s": 100, "hint_after_s": 200}, nudge_s=100, hint_s=200)
    st = _st(autonomy_level=2, state="active")
    st.last_progress_ts = time.time() - 300   # past hint threshold
    st.last_activity_ts = time.time() - 300
    d = p.evaluate(st)
    assert d.may_proactive
    assert d.urgency in ("medium", "high")


def test_checkpoint_matcher():
    m = CheckpointMatcher([
        {"id": "c-scan", "name": "scan", "detect": {"command_match": r"nmap"}},
        {"id": "c-fuzz", "name": "fuzz", "detect": {"command_match": r"(gobuster|ffuf|feroxbuster)"}},
    ])
    assert m.check("nmap -sV 10.1.0.5") == ["c-scan"]
    assert m.check("ffuf -w x -u y/FUZZ") == ["c-fuzz"]
    assert m.check("ls -la") == []


def test_matcher_target_placeholder():
    m = CheckpointMatcher([
        {"id": "c1", "detect": {"command_match": r"nmap {target_net}"}},
    ])
    assert m.check("nmap 10.9.0.12") == ["c1"]


def test_state_caps_command_history():
    st = SessionState(session_id=1)
    for i in range(600):
        st.add_command(time.time(), f"cmd{i}")
    assert len(st.commands) == 400
    assert st.recent_commands(3) == ["cmd597", "cmd598", "cmd599"]
