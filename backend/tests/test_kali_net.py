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
            import re as _re
            m = _re.search(r"@@OK:(\w+)@@", cmd)
            tok = m.group(1) if m else ""
            return {"out": f"@@OK:{tok}@@\nzsh\n@@SEP:{tok}@@\n$ ",
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
    from types import SimpleNamespace

    from app.services.coach_bridge import exec_visible_in_kali
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


async def test_exec_window_targets_named_worker_pane():
    """window=w1 routes every pane op to pentrain-coach:w1 — and the window
    ensure rides inside the ONE batched probe, not an extra QGA call."""
    from types import SimpleNamespace

    from app.services.coach_bridge import exec_visible_in_kali
    pve = _TmuxPve()
    engine = SimpleNamespace(pve=pve)
    res = await exec_visible_in_kali(engine, 100, "id", timeout_s=10,
                                   window="w1")
    assert res["exitcode"] == 0 and "hello-out" in res["out"]
    # ensure fragment (list-windows || new-window) inside the ONE probe
    assert sum("list-windows" in c and "new-window" in c
               for c in pve.calls) == 1
    pane_ops = [c for c in pve.calls if "send-keys" in c
                or "display-message" in c or "capture-pane" in c]
    assert pane_ops and all("-t pentrain-coach:w1" in c for c in pane_ops)


def test_exec_window_rejects_target_injection():
    """tmux target syntax must stay a bare window name — anything else is
    a shell/target injection attempt."""
    from pydantic import ValidationError

    from app.schemas import CoachExecIn
    CoachExecIn(session_id=1, command="id", window="w1")
    CoachExecIn(session_id=1, command="id")
    for bad in ("w-1;rm", "x y", "a:b", "0" * 20, "UPPER"):
        import pytest
        with pytest.raises(ValidationError):
            CoachExecIn(session_id=1, command="id", window=bad)


# ---------------- range→platform control plane ----------------

def test_api_ip_port_parsing():
    from app.services.sessions import _api_ip_port
    assert _api_ip_port("http://192.0.2.10:8000") == ("192.0.2.10", 8000)
    assert _api_ip_port("192.0.2.10:9000") == ("192.0.2.10", 9000)
    assert _api_ip_port("https://10.0.0.7") == ("10.0.0.7", 443)
    # hostnames can't become ludus rules (no DNS inside the range)
    assert _api_ip_port("http://pentrain-app:8000") == (None, 8000)
    assert _api_ip_port(None) == (None, 8000)
    assert _api_ip_port("") == (None, 8000)


def test_compile_topology_no_platform_rule():
    # the control-plane hole is the testing-mode allow list — a ludus
    # firewall rule can't express a literal public IP (renders as
    # "10.1.public.10" and kills the deploy's iptables task)
    from types import SimpleNamespace

    from app.services.sessions import compile_topology
    cfg = compile_topology(SimpleNamespace(topology={}))
    assert "network" not in cfg


def test_merge_testing_allow_appends_api():
    from app.services.sessions import _merge_testing_allow
    assert _merge_testing_allow([], "192.0.2.10") == ["192.0.2.10/32"]
    assert _merge_testing_allow(["1.2.3.0/24"], "192.0.2.10") == \
        ["1.2.3.0/24", "192.0.2.10/32"]
    # idempotent + None-safe
    assert _merge_testing_allow(["192.0.2.10/32"], "192.0.2.10") == \
        ["192.0.2.10/32"]
    assert _merge_testing_allow(["1.2.3.0/24"], None) == ["1.2.3.0/24"]


def test_guest_scripts_pin_api_route():
    from app.services.kali_net import _guest_bringup, _guest_release
    b = _guest_bringup("aa:bb:cc:dd:ee:ff", [], api_host="192.0.2.10")
    assert "API_HOST='192.0.2.10'" in b
    assert 'route replace "$API_HOST"/32 via "$RDNS" dev eth0' in b
    r = _guest_release("aa:bb:cc:dd:ee:ff", api_host="192.0.2.10")
    assert 'ip route del "$API_HOST"/32' in r
    # without an api host the guards stay inert (empty var, [ -n ] skips)
    b2 = _guest_bringup("aa:bb:cc:dd:ee:ff", [])
    assert "API_HOST=''" in b2


def test_guest_scripts_pure_ascii():
    # qemu guest-file-write 500s on wide chars — assert the invariant
    from app.services.kali_net import _guest_bringup, _guest_release
    _guest_bringup("bc:24:11:22:33:44", ["pentrain-x:21", "x:21"],
                   "192.0.2.10").encode("ascii")
    _guest_bringup("bc:24:11:22:33:44", [], None).encode("ascii")
    _guest_release("bc:24:11:22:33:44", "192.0.2.10").encode("ascii")


async def test_testing_mode_installs_router_allow_via_qga(monkeypatch):
    # POST /testing/allow is a silent no-op on ludus 2 (LUDUS_TESTING stays
    # empty) — testing_mode must also push the ACCEPTs onto the router's
    # LUDUS_USER_RULES chain through the qemu agent, idempotently.
    from app.ranges.ludus import LudusProvider

    pve = _FakePve()
    prov = LudusProvider("https://ludus:8080", "k", pve)
    calls: list[tuple[str, str]] = []

    async def fake_req(method, path, **kw):
        calls.append((method, path))
        if path == "/range":
            return {"VMs": [{"proxmoxID": 102, "isRouter": True},
                            {"proxmoxID": 103}]}
        return {}

    monkeypatch.setattr(prov, "_req", fake_req)
    await prov.testing_mode(True, allow_ips=["192.0.2.10/32", "10.9.9.9/32"])
    await prov._client.aclose()

    assert ("POST", "/testing/allow") in calls
    assert len(pve.sh_calls) == 2
    for cidr, cmd in zip(["192.0.2.10/32", "10.9.9.9/32"], pve.sh_calls, strict=False):
        assert f"iptables -C LUDUS_USER_RULES -d {cidr} -j ACCEPT" in cmd
        assert f"iptables -I LUDUS_USER_RULES 1 -d {cidr} -j ACCEPT" in cmd

    # idempotent second run still issues the -C||-I form (no dupes live)
    pve.sh_calls.clear()
    await prov.testing_mode(True, allow_ips=["192.0.2.10/32"])
    assert len(pve.sh_calls) == 1


async def test_testing_mode_router_allow_survives_missing_router(monkeypatch):
    from app.ranges.ludus import LudusProvider

    pve = _FakePve()
    prov = LudusProvider("https://ludus:8080", "k", pve)

    async def fake_req(method, path, **kw):
        if path == "/range":
            return {"VMs": [{"proxmoxID": 103}]}
        return {}

    monkeypatch.setattr(prov, "_req", fake_req)
    await prov.testing_mode(True, allow_ips=["192.0.2.10/32"])
    await prov._client.aclose()
    assert pve.sh_calls == []

    # disable never touches the router
    await prov.testing_mode(False)
    assert pve.sh_calls == []


async def test_soft_reset_reapplies_testing_allow(db, monkeypatch):
    """Disk-only rollback wipes router iptables — the testing allow rules
    (api egress for telemetry/terminal) must be re-installed on reset."""
    calls: list[list | None] = []

    async def fake_tm(enable, allow_ips=None):
        calls.append(allow_ips)

    from app.models.domain import Quest, Track
    from app.services import engine as engine_svc
    from app.services import sessions as sessions_svc
    from app.services import settings as settings_svc
    db.add(Track(slug="t", title="t"))
    db.add(Quest(id="q", track_slug="t", tier=1, title="q", pack_path="/x"))
    await settings_svc.patch_settings(
        db, {"platform.api_url": "http://192.0.2.10:8000"})
    engine = await engine_svc.get_engine(db)
    p = engine.provider
    monkeypatch.setattr(p, "testing_mode", fake_tm)
    await p.deploy_range("x", {"ludus": [{"vm_name": "MO-kali"}]})
    rid = next(iter(p._ranges))
    from app.ranges.base import RangeState
    p._ranges[rid].state = RangeState.RUNNING
    await p.snapshot_all(rid, "pentrain-postdeploy")

    s = Session(quest_id="q", state="ready", range_id=rid)
    db.add(s)
    await db.commit()
    await sessions_svc._reset(s.id, hard=False)
    assert calls and calls[-1] == ["192.0.2.10/32"]
