"""Cross-quest topology validation — every pack must compile to a sane Ludus
config: unique IPs per VLAN, resolvable flag→vm references, no windows+
command-flag combos (POSIX-shell check would never run)."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.packs import discover_quests
from app.services.sessions import compile_topology

PACKS = Path(__file__).resolve().parents[2] / "content" / "packs"


def _quests():
    found, errors = discover_quests(PACKS)
    assert not errors, f"pack errors: {errors}"
    return found


def test_all_quests_compile():
    found = _quests()
    assert len(found) >= 5
    for _qdir, spec in found:
        cfg = compile_topology(SimpleNamespace(topology=spec.topology.model_dump()))
        vms = cfg["ludus"]
        assert vms, f"{spec.meta.id}: empty topology"
        names = [v["vm_name"] for v in vms]
        assert len(names) == len(set(names)), f"{spec.meta.id}: duplicate vm names"
        # unique ip_last_octet within each vlan
        seen: dict[tuple[int, int], str] = {}
        for v in vms:
            key = (v["vlan"], v["ip_last_octet"])
            assert key not in seen, (
                f"{spec.meta.id}: {v['vm_name']} and {seen[key]} share "
                f"vlan{key[0]}.x.{key[1]}")
            seen[key] = v["vm_name"]


def test_flag_vm_references_resolve():
    for _qdir, spec in _quests():
        vms = {v.name for v in spec.topology.vms}
        for f in spec.flags:
            target = f.vm if f.kind == "file" else (f.command or {}).get("vm")
            assert target in vms | {"kali"}, \
                f"{spec.meta.id}: flag {f.id} → unknown vm {target}"


def test_windows_fields_pass_through_compile():
    """windows/domain dicts must survive compile_topology into the Ludus config."""
    for _qdir, spec in _quests():
        cfg = compile_topology(SimpleNamespace(topology=spec.topology.model_dump()))
        by_name = {v["vm_name"]: v for v in cfg["ludus"]}
        for v in spec.topology.vms:
            entry = by_name[f"{{{{ range_id }}}}-{v.name}"]
            if v.windows:
                assert entry["windows"] == v.windows and entry["linux"] is False, \
                    f"{spec.meta.id}: {v.name} lost windows passthrough"
            if v.domain:
                assert entry["domain"] == v.domain, \
                    f"{spec.meta.id}: {v.name} lost domain passthrough"


def test_gpos_fold_into_windows_key():
    """VmSpec.gpos must land under windows.gpos in the Ludus config."""
    cfg = compile_topology(SimpleNamespace(topology={
        "vms": [{"name": "dc01", "template": "win2022-server-x64-template",
                 "linux": False, "gpos": ["disable_defender"]}]}))
    entry = next(v for v in cfg["ludus"] if "dc01" in v["vm_name"])
    assert entry["windows"]["gpos"] == ["disable_defender"]
    assert entry["linux"] is False


def test_checkpoint_regexes_compile():
    for _qdir, spec in _quests():
        for cp in spec.coach.checkpoints:
            pat = (cp.detect or {}).get("command_match")
            if pat:
                re.compile(pat), f"{spec.meta.id}: bad regex {pat}"


def test_flag_ids_unique_per_quest():
    for _qdir, spec in _quests():
        ids = [f.id for f in spec.flags]
        assert len(ids) == len(set(ids)), f"{spec.meta.id}: duplicate flag ids"


def test_hint_stages_valid():
    ok = {"recon", "enum", "exploit", "privesc", "pivot", "post", "general",
          "triage", "analysis", "persistence"}  # forensics stages are legit too
    for _qdir, spec in _quests():
        for h in spec.hints:
            assert h.stage in ok, f"{spec.meta.id}: hint {h.id} bad stage {h.stage!r}"


def test_new_audit_quests_are_lightweight_and_local():
    expected = {
        "ai-t1-rag-audit", "ai-t1-tool-exam",
        "ai-t2-mcp-review", "ai-t2-model-review", "ai-t2-exam",
        "ai-t3-agent-review", "ai-t3-exam",
        "cloud-t1-rbac-review", "cloud-t1-gitops-review", "cloud-t1-exam",
        "cloud-t1-container-review",
        "cloud-t2-metadata-review", "cloud-t2-exam",
        "cloud-t3-gitops-review", "cloud-t3-exam",
        "exp-t1-source-review", "exp-t1-pipeline-review", "exp-t1-exam",
        "exp-t1-serialization-review", "exp-t2-binary-review", "exp-t2-exam",
        "exp-t3-cve-review", "exp-t3-exam",
        "web-t3-template-review", "linux-t3-capability-review",
        "cap-t4-neuralswarm",
    }
    specs = {spec.meta.id: spec for _, spec in _quests()}
    assert expected <= specs.keys()
    for quest_id in expected:
        spec = specs[quest_id]
        assert spec.topology.vms == [], f"{quest_id}: audit fixture must not deploy a target"
        assert spec.topology.kali.ram_gb == 6
        assert spec.topology.kali.roles
        assert all(flag.kind == "command" and
                   (flag.command or {}).get("vm") == "kali"
                   for flag in spec.flags), quest_id
    for track in ("ai-security", "cloud-native", "exploits"):
        for tier in (1, 2, 3):
            quests = [spec for spec in specs.values()
                      if spec.meta.track == track and spec.meta.tier == tier]
            assert any(not spec.meta.exam for spec in quests), (track, tier, "teaching quest missing")
            assert any(spec.meta.exam for spec in quests), (track, tier, "exam missing")
