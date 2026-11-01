"""objective — deterministic next-step tracker (mini-PTG) priorities."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.facts import FactsDB
from coach.objective import next_objective, render

CTX = {
    "quest": {"targets": [{"name": "web01", "ip": "10.1.10.21"},
                          {"name": "db01", "ip": "10.1.10.22"}],
              "checkpoints": []},
    "flags": [{"key": "flag-1", "solved": False},
              {"key": "flag-2", "solved": False}],
}


def _ctx(**kw):
    c = {"quest": {"targets": list(CTX["quest"]["targets"]),
                   "checkpoints": []},
         "flags": [dict(f) for f in CTX["flags"]]}
    c.update(kw)
    return c


def _st():
    return SimpleNamespace(checkpoints_hit=set())


def test_unsubmitted_flag_wins():
    f = FactsDB()
    f.flag_seen("pentrAIn{x}")
    f.files["/r/s.py"] = type("FF", (), {"kind": "script", "writes": 3,
                                       "runs": 0, "last_exit": None})()
    ph, obj = next_objective(_ctx(), f, _st())
    assert ph == "objective" and "pentrAIn{x}" in obj


def test_submitted_flag_falls_through_to_script_debt():
    f = FactsDB()
    f.flag_seen("pentrAIn{x}")
    f.flag_mark_submitted("pentrAIn{x}", True)
    f.observe_output("cat > /r/s.py << 'EOF'\nx\nEOF", "", 0)
    ph, obj = next_objective(_ctx(), f, _st())
    assert ph == "execute" and "/r/s.py" in obj


def test_failed_run_asks_for_debug_not_rewrite():
    f = FactsDB()
    f.observe_output("cat > /r/s.py << 'EOF'\nx\nEOF", "", 0)
    f.observe_output("python3 /r/s.py", "boom", 1)
    ph, obj = next_objective(_ctx(), f, _st())
    assert ph == "debug" and "exited 1" in obj


def test_untested_cred_names_a_host():
    f = FactsDB()
    f.add_cred("svc", "s3cret", "loot.txt")
    ph, obj = next_objective(_ctx(), f, _st())
    assert ph == "access" and "web01" in obj and "s3cret" in obj


def test_authored_checkpoint_when_no_facts():
    ctx = _ctx()
    ctx["quest"]["checkpoints"] = [
        {"id": "cp1", "name": "recon done"},
        {"id": "cp2", "name": "foothold"}]
    ph, obj = next_objective(ctx, FactsDB(), _st())
    assert ph == "checkpoint" and "recon done" in obj
    st = _st(); st.checkpoints_hit.add("cp1")
    ph, obj = next_objective(ctx, FactsDB(), st)
    assert "foothold" in obj


def test_blind_quest_recon_first():
    f = FactsDB()
    ph, obj = next_objective(_ctx(), f, _st())
    assert ph == "recon" and "web01" in obj and "db01" in obj


def test_scanned_without_ports_asks_for_deeper_enum():
    f = FactsDB()
    f.observe_command("nmap 10.1.10.21")
    f.observe_command("nmap 10.1.10.22")
    ph, obj = next_objective(_ctx(), f, _st())
    assert ph == "enum" and "10.1.10.21" in obj


def test_ports_but_no_valid_cred_points_at_services():
    f = FactsDB()
    f.observe_output("nmap -sV 10.1.10.21",
                     "Nmap scan report for 10.1.10.21\n"
                     "22/tcp open ssh\n80/tcp open http", 0)
    f.observe_output("nmap -sV 10.1.10.22",
                     "Nmap scan report for 10.1.10.22\n22/tcp open ssh", 0)
    ph, obj = next_objective(_ctx(), f, _st())
    assert ph == "foothold" and "10.1.10.21" in obj


def test_valid_cred_moves_to_flag_hunt():
    f = FactsDB()
    f.observe_output("nmap -sV 10.1.10.21",
                     "Nmap scan report for 10.1.10.21\n22/tcp open ssh", 0)
    f.observe_output("nmap -sV 10.1.10.22",
                     "Nmap scan report for 10.1.10.22\n22/tcp open ssh", 0)
    f.add_cred("svc", "x", "loot", valid_on="10.1.10.21")
    ph, obj = next_objective(_ctx(), f, _st())
    assert ph == "objective" and "flag-1" in obj


def test_all_solved_renders_empty():
    ctx = _ctx(flags=[{"key": "flag-1", "solved": True},
                      {"key": "flag-2", "solved": True}])
    assert render(ctx, FactsDB(), _st()) == ""


def test_render_format():
    f = FactsDB()
    f.flag_seen("pentrAIn{y}")
    out = render(_ctx(), f, _st())
    assert out.startswith("CURRENT_OBJECTIVE (objective): submit flag")
