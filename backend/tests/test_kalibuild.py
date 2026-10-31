"""kalibuild service — guided template builder lifecycle."""
from __future__ import annotations

import pytest

from app.services import kalibuild
from app.services import settings as settings_svc

pytestmark = pytest.mark.anyio


class _FakePve:
    """Minimal PVE surface for the builder flow."""
    def __init__(self):
        self.vms: dict[int, dict] = {
            101: {"name": "kali-x64-desktop-template", "template": 1,
                  "status": "stopped"},
            150: {"name": "other-vm", "template": 0, "status": "running"},
        }
        self.configs: dict[int, dict] = {
            101: {"name": "kali-x64-desktop-template", "template": 1,
                  "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1001,tag=10"},
            150: {"name": "other-vm", "net0": "virtio=…,bridge=vmbr0"},
        }
        self.calls: list[tuple] = []
        self._next = 900

    async def cluster_vms(self):
        return [{"vmid": i, **v} for i, v in self.vms.items()]

    async def vm_by_name(self, name):
        for vmid, v in self.vms.items():
            if v["name"] == name:
                return {"vmid": vmid, **v}
        return None

    async def next_vmid(self):
        return self._next

    async def vm_clone(self, vmid, new_vmid, name, *, full=True, timeout_s=900):
        self.calls.append(("clone", vmid, new_vmid, name))
        self.vms[new_vmid] = {"name": name, "template": 0, "status": "stopped"}
        self.configs[new_vmid] = dict(self.configs[vmid])
        self.configs[new_vmid].pop("template", None)
        self.configs[new_vmid]["name"] = name

    async def vm_config_set(self, vmid, **params):
        self.calls.append(("config", vmid, params))
        self.configs[vmid].update(params)

    async def vm_config(self, vmid):
        return dict(self.configs[vmid])

    async def vm_status(self, vmid):
        if vmid not in self.vms:
            raise RuntimeError("no such vm")
        return {"status": self.vms[vmid]["status"]}

    async def vm_start(self, vmid):
        self.vms[vmid]["status"] = "running"

    async def vm_shutdown(self, vmid):
        self.calls.append(("shutdown", vmid))
        self.vms[vmid]["status"] = "stopped"

    async def vm_stop(self, vmid):
        self.calls.append(("stop", vmid))
        self.vms[vmid]["status"] = "stopped"

    async def vm_wait_status(self, vmid, target="stopped", timeout_s=180):
        assert self.vms[vmid]["status"] == target
        return {"status": target}

    async def vm_template(self, vmid, timeout_s=300):
        self.calls.append(("template", vmid))
        self.vms[vmid]["template"] = 1
        self.configs[vmid]["template"] = 1

    async def vm_delete(self, vmid):
        self.calls.append(("delete", vmid))
        self.vms.pop(vmid, None)
        self.configs.pop(vmid, None)


class _Engine:
    def __init__(self, pve):
        self.pve = pve


async def test_list_templates_filters_kali(db):
    pve = _FakePve()
    names = await kalibuild.list_templates(db, _Engine(pve))
    assert names == ["kali-x64-desktop-template"]  # 'other-vm' isn't a template


async def test_start_build_clones_rewires_and_starts(db):
    pve = _FakePve()
    r = await kalibuild.start_build(db, _Engine(pve), "kali-x64-desktop-template")
    assert r["vmid"] == 900 and r["name"] == "pentrain-kali-builder"
    assert ("clone", 101, 900, "pentrain-kali-builder") in pve.calls
    # net0 rewired onto the WAN bridge → builder has real internet
    assert ("config", 900, {"net0": "virtio,bridge=vmbr0"}) in pve.calls
    assert pve.vms[900]["status"] == "running"
    assert await kalibuild.builder_vmid(db) == 900


async def test_start_build_refuses_second_builder(db):
    pve = _FakePve()
    await kalibuild.start_build(db, _Engine(pve), "kali-x64-desktop-template")
    with pytest.raises(kalibuild.BuildError, match="already exists"):
        await kalibuild.start_build(db, _Engine(pve), "kali-x64-desktop-template")


async def test_start_build_requires_template(db):
    pve = _FakePve()
    with pytest.raises(kalibuild.BuildError, match="not found"):
        await kalibuild.start_build(db, _Engine(pve), "nope")
    with pytest.raises(kalibuild.BuildError, match="not a template"):
        await kalibuild.start_build(db, _Engine(pve), "other-vm")


async def test_finalize_converts_and_sets_setting(db):
    pve = _FakePve()
    await kalibuild.start_build(db, _Engine(pve), "kali-x64-desktop-template")
    r = await kalibuild.finalize(db, _Engine(pve))
    assert ("shutdown", 900) in pve.calls and ("template", 900) in pve.calls
    assert r["template"] == "pentrain-kali-builder"   # template keeps the VM name
    assert await settings_svc.get_setting(db, "engine.kali_template") == \
        "pentrain-kali-builder"
    assert await kalibuild.builder_vmid(db) == 0
    # status resets — the template is done
    assert (await kalibuild.status(db, _Engine(pve)))["state"] == "none"


async def test_abandon_deletes_builder(db):
    pve = _FakePve()
    await kalibuild.start_build(db, _Engine(pve), "kali-x64-desktop-template")
    r = await kalibuild.abandon(db, _Engine(pve))
    assert r["ok"] is True
    assert ("delete", 900) in pve.calls
    assert 900 not in pve.vms
    assert await kalibuild.builder_vmid(db) == 0


async def test_status_none_without_builder(db):
    assert (await kalibuild.status(db, _Engine(_FakePve())))["state"] == "none"


async def test_status_reports_running_builder(db):
    pve = _FakePve()
    await kalibuild.start_build(db, _Engine(pve), "kali-x64-desktop-template")
    st = await kalibuild.status(db, _Engine(pve))
    assert st["state"] == "running" and st["vmid"] == 900


async def test_status_recovers_externally_deleted_builder(db):
    pve = _FakePve()
    await kalibuild.start_build(db, _Engine(pve), "kali-x64-desktop-template")
    pve.vms.pop(900)  # someone deleted it in the PVE UI
    st = await kalibuild.status(db, _Engine(pve))
    assert st["state"] == "none" and await kalibuild.builder_vmid(db) == 0


async def test_mock_engine_clean_errors(db):
    class _NoPve:
        pass
    with pytest.raises(kalibuild.BuildError, match="mock"):
        await kalibuild.start_build(db, _NoPve(), "x")
    assert (await kalibuild.status(db, _NoPve()))["state"] == "none"
