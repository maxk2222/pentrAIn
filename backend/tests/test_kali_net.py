"""kali_net service — net1 hot-plug + guest DHCP bring-up, and the live
toggle endpoint wiring."""
from __future__ import annotations

import pytest

from app.api import routes_sessions as rs
from app.models.domain import Session
from app.schemas import InternetIn
from app.services import kali_net

pytestmark = pytest.mark.anyio


class _FakePve:
    def __init__(self, *, config: dict | None = None, sh_out: str = ""):
        self.config = config or {
            "net0": "virtio=BC:24:11:28:04:2D,bridge=vmbr1001,tag=10"}
        self.sh_out = sh_out or "IP=192.168.3.55/24\nIF=eth1\n"
        self.set_calls: list[dict] = []
        self.sh_calls: list[str] = []

    async def vm_status(self, vmid):
        return {"status": "running"}

    async def vm_start(self, vmid):
        return "UPID:mock:start"

    async def agent_ping(self, vmid):
        return True

    async def wait_agent(self, vmid, timeout_s=90):
        return True

    async def vm_config(self, vmid):
        return dict(self.config)

    async def vm_config_set(self, vmid, **params):
        self.set_calls.append(params)
        for k, v in params.items():
            if k == "delete":
                self.config.pop(v, None)
            else:
                # real pveproxy fills in a generated MAC server-side
                if "=" not in str(v).split(",")[0]:
                    v = f"virtio=BC:24:11:99:AA:BB,{v.split(',', 1)[-1]}"
                self.config[k] = v

    async def agent_exec_sh(self, vmid, cmd, timeout_s=120):
        self.sh_calls.append(cmd)
        return {"out": self.sh_out, "err": "", "exitcode": 0}

    async def agent_file_write(self, vmid, path, content):
        # the real client ships scripts via guest-file-write (short exec args
        # only — long exec args wedge the virtio QGA channel)
        self.sh_calls.append(f"FILE {path}")
        self.files = getattr(self, "files", {})
        self.files[path] = content


class _Engine:
    def __init__(self, pve):
        self.pve = pve


NET1 = "virtio=BC:24:11:99:AA:BB,bridge=vmbr0"


async def test_apply_attaches_net1_and_reports_ip():
    pve = _FakePve()
    r = await kali_net.apply_kali_internet(_Engine(pve), 103, "vmbr0")
    assert r["ip"] == "192.168.3.55" and r["iface"] == "eth1"
    assert any("net1" in c and "vmbr0" in c["net1"] for c in pve.set_calls)
    assert "bc:24:11:99:aa:bb" in pve.files["/tmp/pentrain-netup.sh"]  # mac in script


async def test_apply_idempotent_when_net1_present():
    pve = _FakePve(config={"net0": "virtio=BC:24:11:28:04:2D,bridge=vmbr1001",
                           "net1": NET1})
    r = await kali_net.apply_kali_internet(_Engine(pve), 103)
    assert r["ip"] == "192.168.3.55"
    assert not any("net1" in c for c in pve.set_calls)  # only the guest bring-up ran


async def test_apply_no_dhcp_lease_raises():
    pve = _FakePve(sh_out="IF=eth1\n")
    with pytest.raises(RuntimeError, match="DHCP lease"):
        await kali_net.apply_kali_internet(_Engine(pve), 103)


async def test_remove_detaches_net1_and_releases():
    pve = _FakePve(config={"net1": NET1})
    await kali_net.remove_kali_internet(_Engine(pve), 103)
    assert {"delete": "net1"} in pve.set_calls
    assert "net1" not in pve.config
    assert pve.sh_calls  # guest release attempted


async def test_remove_noop_without_net1():
    pve = _FakePve()
    await kali_net.remove_kali_internet(_Engine(pve), 103)
    assert pve.set_calls == [] and pve.sh_calls == []


async def test_mock_engine_apply_is_noop():
    r = await kali_net.apply_kali_internet(object(), 103)
    assert r == {"mock": True}


# ---------- POST /sessions/{id}/internet ----------

async def test_internet_toggle_endpoint_guards(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        await rs.toggle_internet(9999, InternetIn(enabled=True), db=db)
    assert e.value.status_code == 404
    s = Session(quest_id="q", state="deploying", kali_vmid=103)
    db.add(s)
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await rs.toggle_internet(s.id, InternetIn(enabled=True), db=db)
    assert e.value.status_code == 422


async def test_internet_toggle_mock_engine_sets_flag(db):
    s = Session(quest_id="q", state="ready", kali_vmid=103)
    db.add(s)
    await db.commit()
    r = await rs.toggle_internet(s.id, InternetIn(enabled=True), db=db)
    assert r["enabled"] is True and r["ip"] == "10.99.0.42"  # MockPveClient emulates dhcp
    await db.refresh(s)
    assert s.kali_internet is True
    r = await rs.toggle_internet(s.id, InternetIn(enabled=False), db=db)
    assert r["enabled"] is False
    await db.refresh(s)
    assert s.kali_internet is False


async def test_soft_reset_reapplies_internet_flag(db, monkeypatch):
    """Post-rollback the net1 config is re-aligned with the session flag."""
    calls: list[str] = []
    monkeypatch.setattr(kali_net, "apply_kali_internet",
                        lambda *a, **k: calls.append("apply"))
    monkeypatch.setattr(kali_net, "remove_kali_internet",
                        lambda *a, **k: calls.append("remove"))

    from app.models.domain import Quest, Track
    from app.services import engine as engine_svc
    from app.services import sessions as sessions_svc
    db.add(Track(slug="t", title="t"))
    db.add(Quest(id="q", track_slug="t", tier=1, title="q", pack_path="/x"))
    engine = await engine_svc.get_engine(db)
    p = engine.provider
    await p.deploy_range("x", {"ludus": [{"vm_name": "MO-kali"}]})
    rid = next(iter(p._ranges))
    from app.ranges.base import RangeState
    p._ranges[rid].state = RangeState.RUNNING
    await p.snapshot_all(rid, "pentrain-postdeploy")

    for flag, want in ((True, "apply"), (False, "remove")):
        calls.clear()
        s = Session(quest_id="q", state="ready", range_id=rid, kali_vmid=7,
                    kali_internet=flag)
        db.add(s)
        await db.commit()
        await sessions_svc._reset(s.id, hard=False)
        assert want in calls
        await db.delete(s)
        await db.commit()


def test_compile_topology_template_override():
    from types import SimpleNamespace

    from app.services.sessions import compile_topology
    quest = SimpleNamespace(topology={
        "kali": {"template": "quest-specific-tpl"}, "vms": []})
    # explicit override wins over the per-quest template
    cfg = compile_topology(quest, kali_template="custom-tpl")
    assert cfg["ludus"][0]["template"] == "custom-tpl"
    # empty/None falls back to the quest's own template
    cfg = compile_topology(quest)
    assert cfg["ludus"][0]["template"] == "quest-specific-tpl"
    cfg = compile_topology(SimpleNamespace(topology={}), kali_template="mine")
    assert cfg["ludus"][0]["template"] == "mine"
    cfg = compile_topology(SimpleNamespace(topology={}))
    assert cfg["ludus"][0]["template"] == "kali-x64-desktop-template"


class _TmuxPve:
    """Simulates the pentrain-coach tmux marker flow — enough fidelity to
    count how many guest calls one visible exec needs."""
    def __init__(self):
        self.calls: list[str] = []
        self.marker = ""
        self.cmd = ""

    async def agent_exec_sh(self, vmid, cmd, timeout_s=120):
        self.calls.append(cmd)
        if "@@OK:" in cmd:                       # batched probe
            return {"out": "@@OK@@\nzsh\n@@SEP@@\n$ ",
                    "err": "", "exitcode": 0}
        if "send-keys" in cmd and "echo PTN" in cmd:
            # send-batch: echo-marker + command in one call — parse the nonce
            import re as _re
            m = _re.search(r"echo (PTN\w+)A", cmd)
            self.marker = m.group(1) if m else ""
            self.cmd = cmd
            return {"out": "", "err": "", "exitcode": 0}
        if "capture-pane" in cmd:
            # realistic pane: A-marker, typed cmd, output, typed B-echo,
            # B-marker output line (as zsh would render it)
            return {"out": (f"{self.marker}A\nid\nhello-out\n"
                            f"echo {self.marker}B:$?\n{self.marker}B:0\n"),
                    "err": "", "exitcode": 0}
        return {"out": "", "err": "", "exitcode": 0}


async def test_visible_exec_batched_guest_calls():
    """One exec_in_kali used to cost ~12 sequential QGA calls; the batched
    probe/send design must stay near ~4 so chained turns run at LLM pace."""
    from app.services.coach_bridge import exec_visible_in_kali
    from types import SimpleNamespace
    pve = _TmuxPve()
    engine = SimpleNamespace(pve=pve)
    res = await exec_visible_in_kali(engine, 100, "id", timeout_s=10)
    assert res["exitcode"] == 0 and "hello-out" in res["out"]
    # probe(1) + send-batch(1) + poll capture(1) + B-marker send(0 or 1)
    assert len(pve.calls) <= 5, pve.calls
    # the probe ran exactly once — has-session/fg/tail rode in one call
    assert sum("@@OK:" in c for c in pve.calls) == 1


async def test_type_in_pane_batched_guest_calls(db):
    """type_in_pane used 4 guest calls + a 1.2s blind wait; batched it must
    be 2 calls with a short settle."""
    from types import SimpleNamespace
    from app.services import coach_bridge
    s = Session(quest_id="q", state="ready", kali_vmid=100)
    s.autonomy_level = 4
    db.add(s)
    await db.commit()
    pve = _TmuxPve()
    engine = SimpleNamespace(pve=pve)

    async def _engine(_db):
        return engine
    orig = coach_bridge.get_engine
    coach_bridge.get_engine = _engine
    try:
        res = await coach_bridge.type_in_pane(db, s.id, "password123")
    finally:
        coach_bridge.get_engine = orig
    assert res["visible"]
    assert len(pve.calls) <= 3, pve.calls       # probe+type+enter, capture+fg
