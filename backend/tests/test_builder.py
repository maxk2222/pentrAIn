"""AI quest builder — materialize/validate/sync/verify-gate tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config
from app.models.domain import BuilderSession, Quest
from app.services import builder as builder_svc
from app.services import builder_tools
from app.services import packs as packs_svc
from app.services import sessions as sessions_svc

MINIMAL_YAML = """\
apiVersion: pentrain/v1
kind: Quest
meta:
  id: {qid}
  track: {track}
  tier: {tier}
  title: "Demo Build"
  version: 1
display:
  tagline: "builder test quest"
requirements:
  min_ram_gb: 4
  min_vcpus: 2
  min_disk_gb: 20
  est_deploy_min: 5
topology:
  kali: {{template: kali-x64-desktop-template, ram_gb: 4, cpus: 2}}
  vms:
    - name: web01
      template: ubuntu-2204-server-template
      ram_gb: 2
      cpus: 2
      roles: []
      setup:
        files:
          - path: /opt/app/docker-compose.yml
            content: |
              version: "3"
              services: {{}}
        exec:
          - "mkdir -p /opt/labflags"
flags: []
hints: []
coach:
  briefing_ref: coach_context.md
  checkpoints: []
scoring:
  base: 0
  time_bonus_max: 0
  par_s: 0
  hint_cost: 0
  takeover_cost: 0
"""

DRAFT = {
    "quest.yaml": MINIMAL_YAML,
    "briefing.md": "# demo\n",
    "coach_context.md": "# truth\n",
    "defense.md": "# fix\n",
    "cheatsheet.md": "# cmds\n",
}


def _draft(qid="demo-docker", track="custom", tier=1) -> dict:
    return {k: (v.format(qid=qid, track=track, tier=tier)
                if k == "quest.yaml" else v)
            for k, v in DRAFT.items()}


@pytest.fixture
def gen_cfg(tmp_path, monkeypatch):
    """Route generated_packs/content dirs into tmp for the test."""
    cfg = Config(generated_packs_dir=str(tmp_path / "gen"))
    monkeypatch.setattr(builder_svc, "get_config", lambda: cfg)
    monkeypatch.setattr(builder_tools, "get_config", lambda: cfg)
    return cfg


async def _bs(db, **kw) -> BuilderSession:
    bs = BuilderSession(**kw)
    db.add(bs)
    await db.commit()
    return bs


async def test_materialize_happy(db, gen_cfg, tmp_path):
    bs = await _bs(db, title="t")
    errors, qid = await builder_svc._materialize(db, bs, _draft())
    assert errors == [] and qid == "demo-docker"
    root = Path(gen_cfg.generated_packs_dir) / "custom" / "demo-docker"
    assert (root / "quest.yaml").exists()
    assert (root / "flags").is_dir() is False  # no flags dir in this draft
    q = await db.get(Quest, "demo-docker")
    assert q is not None and q.generated is True
    assert q.track_slug == "custom"
    # setup block survived the sync into topology json
    setup = q.topology["vms"][0]["setup"]
    assert setup["files"][0]["path"] == "/opt/app/docker-compose.yml"
    assert setup["exec"] == ["mkdir -p /opt/labflags"]


async def test_materialize_unsafe_paths(db, gen_cfg):
    bs = await _bs(db, title="t")
    d = _draft()
    d["../evil.yaml"] = "x"
    d["/abs/path.md"] = "y"
    errors, _ = await builder_svc._materialize(db, bs, d)
    assert any("unsafe file path" in e for e in errors)


async def test_materialize_bad_id_and_exam(db, gen_cfg):
    bs = await _bs(db, title="t")
    d = _draft(qid="Bad_ID!")
    errors, _ = await builder_svc._materialize(db, bs, d)
    assert any("kebab-case" in e for e in errors)

    d = _draft()
    d["quest.yaml"] = d["quest.yaml"].replace(
        "  version: 1", "  version: 1\n  exam: true")
    errors, _ = await builder_svc._materialize(db, bs, d)
    assert any("exam" in e for e in errors)


async def test_materialize_wrong_track_rejected(db, gen_cfg):
    bs = await _bs(db, title="t")
    errors, _ = await builder_svc._materialize(
        db, bs, _draft(track="web-appsec"))
    assert any("'custom'" in e for e in errors)


async def test_materialize_curated_collision(db, gen_cfg):
    db.add(Quest(id="curated-q", track_slug="web-appsec", tier=1,
                 title="c", pack_path="/x"))
    await db.commit()
    bs = await _bs(db, title="t")
    errors, _ = await builder_svc._materialize(db, bs, _draft(qid="curated-q"))
    assert any("collides" in e for e in errors)


async def test_materialize_missing_role(db, gen_cfg):
    bs = await _bs(db, title="t")
    d = _draft()
    d["quest.yaml"] = d["quest.yaml"].replace(
        "roles: []", 'roles: [definitely-no-such-role]')
    errors, _ = await builder_svc._materialize(db, bs, d)
    assert any("definitely-no-such-role" in e for e in errors)


async def test_materialize_missing_defense(db, gen_cfg):
    bs = await _bs(db, title="t")
    d = _draft()
    del d["defense.md"]
    errors, _ = await builder_svc._materialize(db, bs, d)
    assert any("defense.md" in e for e in errors)


def _seed_pack(qdir: Path, qid: str, track: str = "custom") -> None:
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "quest.yaml").write_text(
        _draft(qid)["quest.yaml"].replace("track: custom", f"track: {track}"))
    for f in ("briefing.md", "coach_context.md", "defense.md"):
        (qdir / f).write_text("# x\n")


async def test_sync_extra_dirs(db, tmp_path):
    """Generated packs sync via extra_dirs and get flagged; a generated pack
    reusing a curated id must NOT shadow it."""
    _seed_pack(tmp_path / "cur" / "track-a" / "q-one", "q-one", "lab")
    _seed_pack(tmp_path / "gen" / "custom" / "q-gen", "q-gen")
    # shadow attempt — same id as curated
    _seed_pack(tmp_path / "gen" / "custom" / "q-one", "q-one")

    res = await packs_svc.sync_packs(db, tmp_path / "cur",
                                     extra_dirs=[tmp_path / "gen"])
    curated = await db.get(Quest, "q-one")
    generated = await db.get(Quest, "q-gen")
    assert curated is not None and curated.generated is False
    assert curated.pack_path.endswith("q-one")
    assert generated is not None and generated.generated is True
    assert any("shadows" in e for e in res.get("errors", []))


async def test_rescue_incomplete(db):
    await _bs(db, title="t", status="verifying")
    n = await builder_svc.rescue_incomplete(db)
    assert n == 1
    bs = (await builder_svc.list_sessions(db))[0]
    assert bs.status == "interrupted"
    assert any("interrupted" in entry["msg"] for entry in bs.log)


async def test_start_verify_mock_skips(db):
    """Mock engine → honest skip, quest stays 'materialized' — never faked."""
    bs = await _bs(db, title="t", status="materialized",
                   quest_id="demo-docker")
    m = await builder_svc.start_verify(db, bs.id)
    assert "skipped" in m.content.lower()
    bs = (await builder_svc.list_sessions(db))[0]
    assert bs.status == "materialized"
    assert any("SKIPPED" in entry["msg"] for entry in bs.log)


async def test_generated_unlock_no_ladder(db):
    """A generated tier-3 quest must not be dead-locked by track progression."""
    db.add(Quest(id="gen-t3", track_slug="custom", tier=3, title="g",
                 pack_path="/x", generated=True))
    await db.commit()
    ok, _ = await sessions_svc.check_unlock(db, await db.get(Quest, "gen-t3"))
    assert ok


def test_tools_phase_gating():
    chat = {t["function"]["name"]
            for t in builder_tools.tools_for_phase("chat", has_verify=False)}
    assert "kali_exec" not in chat
    assert {"quest_catalog", "web_search", "search_technique"} <= chat
    verify = {t["function"]["name"]
              for t in builder_tools.tools_for_phase("verify", has_verify=True)}
    assert "kali_exec" in verify


def test_extract_files():
    good = 'intro\n```draft\n{"files": {"quest.yaml": "a"}}\n```\ntail'
    assert builder_svc._extract_files(good, builder_svc._DRAFT_RE) == \
        {"quest.yaml": "a"}
    assert builder_svc._extract_files("no block", builder_svc._DRAFT_RE) is None
    bad = '```draft\n{not json}\n```'
    assert "__parse_error__" in builder_svc._extract_files(
        bad, builder_svc._DRAFT_RE)
