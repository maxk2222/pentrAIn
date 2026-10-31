"""Guided kali template builder: clone → customize → convert → set setting.

One builder VM at a time (kali.builder_vmid setting tracks it). The builder
is a FULL clone of the chosen base template, rewired: net0 lands on the WAN
bridge so apt/pip/git work while the user customizes. Finalize converts it
to a template and points engine.kali_template at the result — every future
range deploys the custom environment.
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from . import settings as settings_svc

log = structlog.get_logger(__name__)

BUILDER_NAME = "pentrain-kali-builder"
DEFAULT_TEMPLATE_NAME = "pentrain-kali-custom-template"


class BuildError(RuntimeError):
    pass


async def _pve(engine):
    pve = getattr(engine, "pve", None)
    if pve is None:
        raise BuildError("engine has no PVE client (mock mode)")
    return pve


async def builder_vmid(db: AsyncSession) -> int:
    return int(await settings_svc.get_setting(db, "kali.builder_vmid", 0) or 0)


async def list_templates(db: AsyncSession, engine) -> list[str]:
    """Kali-ish templates on the engine — candidates for the base dropdown."""
    pve = await _pve(engine)
    names = [v["name"] for v in await pve.cluster_vms()
             if v.get("template") and "kali" in (v.get("name") or "").lower()]
    return sorted(names)


async def status(db: AsyncSession, engine) -> dict:
    vmid = await builder_vmid(db)
    if not vmid:
        return {"state": "none"}
    pve = await _pve(engine)
    try:
        st = await pve.vm_status(vmid)
    except Exception:
        # builder gone (deleted externally / converted) → reset the marker
        await settings_svc.set_setting(db, "kali.builder_vmid", 0)
        await db.commit()
        return {"state": "none"}
    cfg = await pve.vm_config(vmid)
    if cfg.get("template"):
        # already converted → report the finished template name
        await settings_svc.set_setting(db, "kali.builder_vmid", 0)
        await db.commit()
        return {"state": "none", "template": cfg.get("name")}
    return {"state": st.get("status", "unknown"), "vmid": vmid,
            "name": cfg.get("name")}


async def start_build(db: AsyncSession, engine, base_template: str,
                      name: str | None = None) -> dict:
    """Clone base → standalone builder VM with direct WAN access → start."""
    pve = await _pve(engine)
    if await builder_vmid(db):
        raise BuildError("a builder VM already exists — finalize or abandon it first")
    base = await pve.vm_by_name(base_template)
    if not base:
        raise BuildError(f"base template '{base_template}' not found")
    if not base.get("template"):
        raise BuildError(f"'{base_template}' is a VM, not a template")

    vmid = await pve.next_vmid()
    name = (name or BUILDER_NAME).strip() or BUILDER_NAME
    await pve.vm_clone(base["vmid"], vmid, name, full=True)

    # the clone inherits the template's net0 (range bridge) — rewire it to
    # the WAN bridge so the builder gets real LAN+internet for setup work
    wan = await settings_svc.get_setting(db, "engine.kali_wan_bridge", "vmbr0")
    await pve.vm_config_set(vmid, net0=f"virtio,bridge={wan}")
    await pve.vm_start(vmid)
    await settings_svc.set_setting(db, "kali.builder_vmid", vmid)
    await db.commit()
    await log.ainfo("kali builder started", vmid=vmid, base=base_template)
    return {"vmid": vmid, "name": name, "base": base_template}


async def finalize(db: AsyncSession, engine,
                   template_name: str | None = None) -> dict:
    """Stop builder → convert to template → point engine.kali_template at it."""
    pve = await _pve(engine)
    vmid = await builder_vmid(db)
    if not vmid:
        raise BuildError("no builder VM in progress")
    try:
        st = await pve.vm_status(vmid)
    except Exception as e:
        raise BuildError(f"builder vm {vmid} gone: {e}") from e
    if st.get("status") != "stopped":
        try:
            await pve.vm_shutdown(vmid)
            await pve.vm_wait_status(vmid, "stopped", timeout_s=120)
        except Exception:
            await pve.vm_stop(vmid)          # no guest agent / hard off
            await pve.vm_wait_status(vmid, "stopped", timeout_s=60)

    await pve.vm_template(vmid)
    name = template_name or DEFAULT_TEMPLATE_NAME
    # PVE template name = the VM's name — rename isn't supported, so if the
    # caller picked a fresh name the template still carries the builder's.
    cfg = await pve.vm_config(vmid)
    actual = cfg.get("name") or name
    await settings_svc.set_setting(db, "engine.kali_template", actual)
    await settings_svc.set_setting(db, "kali.builder_vmid", 0)
    await db.commit()
    await log.ainfo("kali template finalized", vmid=vmid, template=actual)
    return {"template": actual}


async def abandon(db: AsyncSession, engine) -> dict:
    """Tear down the in-flight builder without converting it."""
    pve = await _pve(engine)
    vmid = await builder_vmid(db)
    if not vmid:
        return {"ok": True, "note": "nothing to abandon"}
    try:
        st = await pve.vm_status(vmid)
        if st.get("status") == "running":
            await pve.vm_stop(vmid)
            await pve.vm_wait_status(vmid, "stopped", timeout_s=60)
        await pve.vm_delete(vmid)
    except Exception as e:
        raise BuildError(f"abandon failed for vm {vmid}: {e}") from e
    await settings_svc.set_setting(db, "kali.builder_vmid", 0)
    await db.commit()
    return {"ok": True}
