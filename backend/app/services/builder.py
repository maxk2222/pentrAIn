"""AI quest builder — chat → draft → validate → verify orchestration.

Flow per builder session:
  chat turns (clarify/learn/draft) → ```draft block → _materialize writes
  the pack under generated_packs/<id>, validates + syncs it into the DB →
  start_verify deploys it with the coach at autonomy 4 + subagents →
  diagnose failures (quest_bug / too_easy / coach_limitation) → patch →
  hard reset (the deploy snapshot still holds the OLD spec — soft reset
  cannot pick up quest changes) → repeat up to builder.max_verify_iters.
  A clean solve ends 'verified' with a SOFT reset so the session stays
  usable for the human afterwards.

Honesty rules encoded here: mock engine → verification reported skipped,
never "solved"; coach_limitation is reported, not patched around; a
sub-min_solve_s solve counts as too_easy, not success.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import session_factory
from ..models.domain import (
    BuilderMessage,
    BuilderSession,
    CoachAction,
    LlmUsage,
    Quest,
    Session,
    SessionState,
)
from . import builder_tools
from . import packs as packs_svc
from . import sessions as sessions_svc
from . import settings as settings_svc
from .builder_prompts import BUILDER_SYSTEM, DIAGNOSE_SYSTEM
from .engine import get_engine
from .sessions import SessionError

_CHAT_HISTORY = 24
_TOOL_RESULT_MAX = 16_000
_DRAFT_RE = re.compile(r"```draft\s*\n(.*?)\n?```", re.DOTALL)
_VERDICT_RE = re.compile(r"```verdict\s*\n(.*?)\n?```", re.DOTALL)
_SAFE_QID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_SAFE_PATH = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")

_verify_tasks: dict[int, asyncio.Task] = {}


# ---------------------------------------------------------------- helpers

def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _log(db: AsyncSession, bs: BuilderSession, kind: str,
               msg: str) -> None:
    bs.log = (bs.log or []) + [{"ts": _utcnow(), "kind": kind,
                                "msg": msg[:2000]}]
    await db.commit()


async def _msg(db: AsyncSession, bs: BuilderSession, role: str,
               content: str, *, kind: str = "chat",
               meta: dict | None = None) -> BuilderMessage:
    m = BuilderMessage(session_id=bs.id, role=role, kind=kind,
                       content=content, meta=meta or {})
    db.add(m)
    await db.commit()
    return m


async def _llm(db: AsyncSession, messages: list[dict],
               *, tools: list[dict] | None = None) -> dict:
    """One chat/completions call against the configured model, usage-logged."""
    base_url = str(await settings_svc.get_setting(
        db, "llm.base_url", "")).rstrip("/")
    model = str(await settings_svc.get_setting(db, "llm.model", ""))
    api_key = str(await settings_svc.get_setting(db, "llm.api_key", "") or "")
    payload: dict = {
        "model": model,
        "messages": messages[-60:],
        "temperature": float(await settings_svc.get_setting(
            db, "llm.temperature", 0.4) or 0.4),
        # full-pack drafts run ~6-9k tokens — without an explicit cap
        # the server default (often 4k) truncates mid-JSON → parse errors
        "max_tokens": int(await settings_svc.get_setting(
            db, "builder.max_tokens", 12288) or 12288),
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    t0 = time.monotonic()
    async with httpx.AsyncClient(
            # a full-pack draft is ~6-8k tokens — on a loaded local model
            # that's 10+ minutes of generation, well past a default 300s
            timeout=httpx.Timeout(900.0, connect=15.0)) as c:
        r = await c.post(f"{base_url}/chat/completions",
                         json=payload, headers=headers)
        if r.status_code >= 400:
            # keep the server's reason — template/schema errors are
            # otherwise invisible ("400 Bad Request" tells you nothing)
            raise SessionError(f"LLM {r.status_code}: {r.text[:300]}")
        data = r.json()
    usage = data.get("usage") or {}
    db.add(LlmUsage(
        model=model, kind="builder",
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        latency_ms=int((time.monotonic() - t0) * 1000)))
    await db.commit()
    choices = data.get("choices") or []
    return (choices[0].get("message") if choices else {}) or {}


async def _tool_loop(db: AsyncSession, bs: BuilderSession,
                     ctx: builder_tools.ToolCtx, messages: list[dict],
                     tools: list[dict], cap: int) -> str:
    """LLM ↔ tool ping-pong until a plain answer arrives (or cap hits).

    When the call cap is hit mid-exploration the model's last message is
    usually tool_calls-only — returning its (empty) content would post a
    blank reply. Close out with stub results and force one text answer."""
    calls = 0
    while True:
        msg = await _llm(db, messages, tools=tools)
        tcs = msg.get("tool_calls") or []
        if not tcs or calls >= cap:
            content = msg.get("content") or ""
            if content or calls < cap or not tcs:
                return content
            messages.append({"role": "assistant",
                             "content": "", "tool_calls": tcs})
            for tc in tcs:
                messages.append({
                    "role": "tool",
                    "tool_call_id": str(tc.get("id") or ""),
                    "name": str((tc.get("function") or {})
                                .get("name") or ""),
                    "content": "(tool budget for this turn exhausted)"})
            messages.append({"role": "user", "content":
                             "Tool budget for this turn is exhausted — "
                             "reply now with what you have (emit the "
                             "draft block if it was due)."})
            return (await _llm(db, messages)).get("content") or ""
        messages.append({"role": "assistant",
                         "content": msg.get("content") or "",
                         "tool_calls": tcs})
        for tc in tcs:
            if calls >= cap:
                break
            calls += 1
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await builder_tools.dispatch(ctx, name, args)
            await _msg(db, bs, "assistant",
                       f"{name}({json.dumps(args, ensure_ascii=False)[:240]})",
                       kind="tool", meta={"result": result[:600]})
            messages.append({"role": "tool",
                             "tool_call_id": str(tc.get("id") or ""),
                             "name": name,
                             "content": result[:_TOOL_RESULT_MAX]})


async def _history(db: AsyncSession, bs: BuilderSession) -> list[dict]:
    """Conversation history — tool calls are folded into compact memory
    lines so the model remembers what it already read instead of
    re-exploring the catalog every turn (burning the whole call budget)."""
    rows = (await db.execute(
        select(BuilderMessage)
        .where(BuilderMessage.session_id == bs.id,
               BuilderMessage.kind.in_(
                   ["chat", "question", "draft", "tool"]))
        .order_by(BuilderMessage.id.desc())
        .limit(_CHAT_HISTORY * 2))).scalars().all()
    out: list[dict] = []
    for m in reversed(rows):
        if m.kind == "tool":
            res = str((m.meta or {}).get("result") or "")[:500]
            out.append({"role": "assistant", "content":
                        f"[tool call] {m.content[:200]}\n→ {res}"})
        else:
            # bound each turn's content — draft blocks are ~8k chars and
            # two of them in history alone can exceed the loaded ctx
            out.append({"role": m.role,
                        "content": m.content[:4000]})
    out = out[-_CHAT_HISTORY:]
    # chat templates (qwen/jinja) require the first non-system message to
    # be a user turn — mid-conversation windows can start on an assistant
    # tool line → "No user query found in messages" (400)
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


# ------------------------------------------------------------------- chat

async def create(db: AsyncSession, title: str = "") -> BuilderSession:
    bs = BuilderSession(title=(title or "untitled build")[:200])
    db.add(bs)
    await db.commit()
    await _msg(db, bs, "system", "builder session created", kind="status")
    return bs


async def get_or_404(db: AsyncSession, bs_id: int) -> BuilderSession | None:
    return await db.get(BuilderSession, bs_id)


async def chat(db: AsyncSession, bs_id: int, text: str,
               attachments: list[dict] | None = None) -> BuilderMessage:
    bs = await db.get(BuilderSession, bs_id)
    if not bs:
        raise SessionError("builder session not found")
    if bs.status == "verifying":
        raise SessionError("verification is running — wait for it to finish")
    for a in attachments or []:
        name = re.sub(r"[^a-zA-Z0-9._-]", "_", str(a.get("name", "file"))[:80])
        body = str(a.get("content", ""))[:32_000]
        text += f"\n\n--- uploaded file: {name} ---\n{body}\n--- end {name} ---"
    await _msg(db, bs, "user", text)
    if bs.title in ("", "untitled build"):
        bs.title = text.strip().splitlines()[0][:80] or "untitled build"
        await db.commit()

    messages = [{"role": "system", "content": BUILDER_SYSTEM}]
    messages += await _history(db, bs)
    if bs.draft:
        messages.append({"role": "system", "content":
                         "Current draft files on disk: "
                         + ", ".join(sorted(bs.draft))})
    ctx = builder_tools.ToolCtx(
        db=db,
        web_enabled=bool(await settings_svc.get_setting(
            db, "builder.web_enabled", True)))
    cap = int(await settings_svc.get_setting(
        db, "builder.tool_call_cap", 10) or 10)
    tools = builder_tools.tools_for_phase("chat", has_verify=False)
    try:
        reply = await _tool_loop(db, bs, ctx, messages, tools, cap)
    except Exception as e:
        # an unreachable/misbehaving LLM is an honest error, not a 500
        return await _msg(
            db, bs, "assistant",
            f"[builder] LLM call failed: {type(e).__name__}: {e} — "
            "check llm.base_url/llm.model in Settings.",
            kind="error")

    files = _extract_files(reply, _DRAFT_RE)
    if files is None and not (reply or "").strip():
        # blank model turn (budget-exhausted/whitespace) — say so instead
        # of posting an empty bubble
        return await _msg(
            db, bs, "assistant",
            "[builder] the model returned an empty response (usually a "
            "sign it ran out of tool budget mid-exploration). Try again — "
            "it remembers the tool results from this turn.",
            kind="error")
    kind = "chat"
    if files is not None:
        kind = "draft"
        errors, qid = await _materialize(db, bs, files)
        # up to two auto-repair rounds: feed validator/parse failures
        # back — a truncated JSON block is cheap to re-emit
        for attempt in range(2):
            if not errors:
                break
            await _log(db, bs, "validate",
                       f"draft rejected ({attempt + 1}/2): {errors[0]}")
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content":
                             "Validation failed — fix and re-emit the WHOLE "
                             "draft block:\n- " + "\n- ".join(errors[:12])})
            reply = await _tool_loop(db, bs, ctx, messages, tools, cap)
            files = _extract_files(reply, _DRAFT_RE)
            errors, qid = (await _materialize(db, bs, files)
                           if files is not None
                           else (["no draft block"], qid))
        if errors:
            return await _msg(
                db, bs, "assistant",
                reply + "\n\n[builder] draft still invalid:\n- "
                + "\n- ".join(errors), kind="error")
        bs.status = "materialized"
        bs.quest_id = qid
        bs.draft = files
        bs.iterations = 0
        await db.commit()
        await _log(db, bs, "draft", f"materialized quest '{qid}'")
    return await _msg(db, bs, "assistant", reply, kind=kind)


_ANY_BLOCK_RE = re.compile(r"```(?:json|draft|yaml)?\s*\n(.*?)```",
                           re.DOTALL)
_FILE_BLOCK_RE = re.compile(
    r"```file:([A-Za-z0-9._/-]+)\s*\n(.*?)```", re.DOTALL)


def _extract_files(text: str, pattern: re.Pattern) -> dict | None:
    """Pull pack files out of the reply. Preferred transport is one
    ```file:<path> fenced block per file — file contents stay verbatim,
    no JSON escaping of YAML/markdown (which models mangle reliably).
    Legacy fallback: a ```draft/```json block containing {"files":…}."""
    named = _FILE_BLOCK_RE.findall(text or "")
    if named:
        return {path.strip(): body.lstrip("\n")
                for path, body in named}
    m = pattern.search(text or "")
    blocks = [m.group(1)] if m else \
        [b for b in _ANY_BLOCK_RE.findall(text or "")]
    if not blocks:
        return None
    for body in blocks:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        files = payload.get("files")
        if isinstance(files, dict):
            return files
    return {"__parse_error__": "no fenced block with a 'files' object"}


# ------------------------------------------------------------- materialize

async def _materialize(db: AsyncSession, bs: BuilderSession,
                       files: dict) -> tuple[list[str], str | None]:
    """Write draft files under generated_packs/<qid>, validate, sync.
    Returns (errors, quest_id)."""
    if "__parse_error__" in files:
        return [files["__parse_error__"]], None
    raw_yaml = files.get("quest.yaml")
    if not isinstance(raw_yaml, str) or not raw_yaml.strip():
        return ["quest.yaml missing from draft"], None
    try:
        meta = (yaml.safe_load(raw_yaml) or {}).get("meta") or {}
    except yaml.YAMLError as e:
        return [f"quest.yaml invalid YAML: {e}"], None
    qid = str(meta.get("id") or "")
    errors: list[str] = []
    if not _SAFE_QID.match(qid):
        errors.append(f"meta.id '{qid}' must be kebab-case [a-z0-9-]")
    if meta.get("track") not in (None, "custom"):
        errors.append("meta.track must be 'custom' for generated quests")
    else:
        files["quest.yaml"] = _force_track(raw_yaml)
    if meta.get("exam"):
        errors.append("generated quests cannot be exams")

    clean: dict[str, str] = {}
    for p, content in files.items():
        rel = str(p).strip().lstrip("/")
        parts = rel.split("/")
        if (not rel or ".." in parts or not _SAFE_PATH.match(rel)
                or rel.startswith("/")):
            errors.append(f"unsafe file path '{p}'")
            continue
        clean[rel] = "" if content is None else str(content)
    if errors:
        return errors, qid or None

    existing = await db.get(Quest, qid)
    if existing and not existing.generated:
        return [f"id '{qid}' collides with a curated quest — pick another"], \
            qid

    # discover_quests expects <root>/<track>/<quest> — generated packs all
    # sit in the custom lane
    root = Path(get_config().generated_packs_dir) / "custom" / qid
    try:
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        for rel, content in clean.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)
    except OSError as e:
        return [f"cannot write pack dir {root}: {e} — check "
                "PENTRAIN_GENERATED_PACKS_DIR is writable"], qid

    spec, verrs = packs_svc.validate_quest_dir(root)
    if verrs:
        # clean up — a rejected pack left on disk would otherwise sneak
        # into the library on the next boot-time rescan
        shutil.rmtree(root, ignore_errors=True)
        return verrs, qid
    if spec is not None:
        verrs = packs_svc.check_role_refs(
            spec, _roles_dir())
        if verrs:
            shutil.rmtree(root, ignore_errors=True)
            return verrs, qid
    await packs_svc.sync_packs(db, get_config().content_dir,
                               extra_dirs=[get_config().generated_packs_dir])
    return [], qid


def _roles_dir() -> Path:
    cfg_dir = Path(get_config().roles_dir)
    if cfg_dir.is_dir():
        return cfg_dir
    return Path(__file__).resolve().parents[3] / "content" / "ansible-roles"


def _force_track(raw_yaml: str) -> str:
    """Rewrite meta.track → custom (LLM often copies the exemplar's track)."""
    try:
        doc = yaml.safe_load(raw_yaml) or {}
        (doc.setdefault("meta", {}))["track"] = "custom"
        return yaml.safe_dump(doc, sort_keys=False)
    except yaml.YAMLError:
        return raw_yaml


# ------------------------------------------------------------------ verify

async def start_verify(db: AsyncSession, bs_id: int) -> BuilderMessage:
    bs = await db.get(BuilderSession, bs_id)
    if not bs:
        raise SessionError("builder session not found")
    if bs.id in _verify_tasks and not _verify_tasks[bs.id].done():
        raise SessionError("verification already running")
    if not bs.quest_id or bs.status not in (
            "materialized", "verified", "verified-partial", "failed",
            "interrupted"):
        raise SessionError("no materialized quest to verify — draft first")

    engine = await get_engine(db)
    if engine.mode == "mock":
        await _log(db, bs, "verify",
                   "verification SKIPPED — mock engine, no real range. "
                   "Quest stays 'materialized', not 'verified'.")
        return await _msg(db, bs, "assistant",
                          "verification skipped — engine is in mock mode; "
                          "a real solve cannot be claimed. The quest is "
                          "materialized and valid but NOT verified.",
                          kind="status")

    bs.status = "verifying"
    bs.iterations = 0
    await db.commit()
    await _log(db, bs, "verify", "verification started (L4 + subagents)")
    _verify_tasks[bs.id] = asyncio.create_task(_verify_loop(bs.id))
    return await _msg(db, bs, "assistant",
                      "verification started — deploying the quest and letting "
                      "the coach solve it at autonomy 4 with subagents. "
                      "I'll watch the run and patch if needed.",
                      kind="status")


async def _verify_loop(bs_id: int) -> None:
    async with session_factory()() as db:
        bs = await db.get(BuilderSession, bs_id)
        try:
            max_iters = int(await settings_svc.get_setting(
                db, "builder.max_verify_iters", 3) or 3)
            timeout_s = int(await settings_svc.get_setting(
                db, "builder.verify_timeout_s", 5400) or 5400)
            for it in range(1, max_iters + 1):
                bs = await db.get(BuilderSession, bs_id)
                bs.iterations = it
                await db.commit()
                await _log(db, bs, "verify", f"iteration {it}/{max_iters}")
                s = None
                prev = None
                try:
                    prev = (await db.get(Session, bs.verify_session_id)
                            if bs.verify_session_id else None)
                    if prev and prev.state not in (
                            SessionState.ABORTED.value,
                            SessionState.ABORTING.value,
                            SessionState.FAILED.value):
                        # subsequent iterations: hard-reset so the PATCHED
                        # spec deploys (soft reset = stale snapshot)
                        await sessions_svc.reset(db, prev.id, hard=True)
                        s = prev
                    else:
                        s = await sessions_svc.create_session(
                            db, bs.quest_id, autonomy_level=4,
                            subagents_enabled=True)
                        bs.verify_session_id = s.id
                        await db.commit()
                except Exception as e:
                    # deploy-time faults (bad template/role, capacity) are
                    # quest bugs the diagnosis loop can patch — don't bail
                    outcome, detail = "deploy_failed", \
                        f"cannot start verify session: {e}"
                    s = prev
                else:
                    outcome, detail = await _await_solve(
                        db, bs, s.id, timeout_s)
                await _log(db, bs, "verify",
                           f"iteration {it} outcome: {outcome} — {detail[:300]}")
                if outcome == "solved":
                    try:
                        await sessions_svc.reset(db, s.id, hard=False)
                    except Exception as e:
                        await _log(db, bs, "verify",
                                   f"soft reset failed: {e!r}")
                    await _finish(db, bs, "verified",
                                  f"coach solved it in {detail}. Session "
                                  f"#{s.id} soft-reset and left open.")
                    return
                verdict = await _diagnose(db, bs, s, outcome, detail)
                kind = str(verdict.get("kind") or "")
                patch_files = verdict.get("patch_files")
                await _log(db, bs, "diagnose",
                           f"{kind}: {verdict.get('rationale', '')[:400]}")
                if kind == "coach_limitation" or not patch_files:
                    await _finish(
                        db, bs, "failed" if kind != "too_easy"
                        else "verified-partial",
                        f"{kind}: {verdict.get('rationale', '')}")
                    return
                # the verdict's patch only carries CHANGED files — overlay
                # it on the current draft or the untouched pack files
                # (briefing/coach_context/defense) get wiped on rewrite
                merged = {**(bs.draft or {}), **patch_files}
                errors, qid = await _materialize(db, bs, merged)
                if errors:
                    await _finish(db, bs, "failed",
                                  "diagnose patch invalid: "
                                  + "; ".join(errors[:4]))
                    return
                bs.quest_id = qid or bs.quest_id
                bs.draft = merged
                await db.commit()
                # next loop iteration hard-resets the same session row
            await _finish(db, bs, "verified-partial",
                          f"exhausted {max_iters} verify iterations — quest "
                          "improved each round but no clean solve")
        except Exception as e:
            with contextlib.suppress(Exception):
                await _finish(db, bs, "failed", f"verify crashed: {e!r}")
        finally:
            _verify_tasks.pop(bs_id, None)


async def _await_solve(db: AsyncSession, bs: BuilderSession, sid: int,
                       timeout_s: int) -> tuple[str, str]:
    """Poll the verify session until terminal/stuck/timeout."""
    deadline = time.monotonic() + timeout_s
    stuck_s = int(await settings_svc.get_setting(
        db, "builder.stuck_after_s", 1200) or 1200)
    min_solve = int(await settings_svc.get_setting(
        db, "builder.min_solve_s", 120) or 120)
    t0 = time.monotonic()
    last_n, last_progress = -1, time.monotonic()
    while time.monotonic() < deadline:
        await asyncio.sleep(15)
        s = await db.get(Session, sid)
        if s is None:
            return "failed", "session row gone"
        await db.refresh(s)
        if s.state == SessionState.SOLVED.value:
            secs = int(time.monotonic() - t0)
            if s.started_at and s.ended_at:
                secs = max(1, int((s.ended_at - s.started_at)
                                  .total_seconds()))
            if secs < min_solve:
                return "too_easy", f"solved in {secs}s (< {min_solve}s floor)"
            return "solved", f"{secs}s"
        if s.state in (SessionState.ABORTED.value,
                       SessionState.FAILED.value):
            return "failed", s.error or s.state
        if s.state == SessionState.READY.value:
            # deploy finished — the coach only attaches on 'active'. Same
            # for hard-reset redeploys; 409s mean someone beat us to it.
            with contextlib.suppress(Exception):
                await sessions_svc.activate(db, s.id)
            continue
        n = int((await db.execute(
            select(func.count()).select_from(CoachAction)
            .where(CoachAction.session_id == sid))).scalar() or 0)
        if n != last_n:
            last_n, last_progress = n, time.monotonic()
        elif (s.state == SessionState.ACTIVE.value
              and time.monotonic() - last_progress > stuck_s):
            return "stuck", f"no coach progress for {stuck_s}s"
    return "timeout", f"no solve within {timeout_s}s"


async def _diagnose(db: AsyncSession, bs: BuilderSession,
                    s: Session | None, outcome: str, detail: str) -> dict:
    """Ask the LLM to classify the failure; it gets live verify tools."""
    quest = await db.get(Quest, bs.quest_id)
    actions = []
    if s is not None:
        actions = (await db.execute(
            select(CoachAction).where(CoachAction.session_id == s.id)
            .order_by(CoachAction.id.desc()).limit(40))).scalars().all()
    tail = "\n".join(
        f"{a.tool}({json.dumps(a.args or {})[:140]}) → "
        f"{str(a.result or '')[:200]}"
        for a in reversed(actions)) or "(no coach actions recorded)"
    spec = yaml.safe_dump({
        "quest.yaml": (bs.draft or {}).get("quest.yaml", ""),
        "deploy_log_tail": (s.deploy_log or "")[-3000:] if s else "",
    }, sort_keys=False)
    messages = [
        {"role": "system", "content": DIAGNOSE_SYSTEM},
        {"role": "user", "content":
         f"Quest '{bs.quest_id}' (track {quest.track_slug if quest else '?'})\n"
         f"Outcome: {outcome} — {detail}\n\n"
         f"--- spec + deploy log ---\n{spec[:12000]}\n\n"
         f"--- coach action tail ---\n{tail[:12000]}\n\n"
         "Verdict?"}]
    engine = await get_engine(db)
    ctx = builder_tools.ToolCtx(
        db=db, engine=engine,
        verify_session_id=s.id if s is not None else None,
        web_enabled=bool(await settings_svc.get_setting(
            db, "builder.web_enabled", True)))
    cap = int(await settings_svc.get_setting(
        db, "builder.tool_call_cap", 10) or 10)
    tools = builder_tools.tools_for_phase("verify",
                                          has_verify=s is not None)
    reply = await _tool_loop(db, bs, ctx, messages, tools, cap)
    m = _VERDICT_RE.search(reply or "")
    if not m:
        return {"kind": "coach_limitation",
                "rationale": "diagnosis produced no verdict block — "
                             "treating as inconclusive/coach-side"}
    try:
        verdict = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {"kind": "coach_limitation",
                "rationale": "verdict block was not valid JSON"}
    # patch files ride as ```file:<path> blocks in the same reply —
    # or (legacy) embedded in the verdict's patch.files object
    patch_files = _extract_files(reply, _DRAFT_RE) or {}
    if "__parse_error__" in patch_files:
        patch_files = {}
    patch = verdict.get("patch")
    if not patch_files and isinstance(patch, dict) \
            and isinstance(patch.get("files"), dict):
        patch_files = patch["files"]
    verdict["patch_files"] = patch_files
    return verdict


async def _finish(db: AsyncSession, bs: BuilderSession, status: str,
                  note: str) -> None:
    bs.status = status
    await db.commit()
    await _log(db, bs, "verify", f"FINAL {status}: {note[:400]}")
    kind = "status" if status == "verified" else "error"
    await _msg(db, bs, "assistant",
               f"verification {status}: {note}", kind=kind)


async def rescue_incomplete(db: AsyncSession) -> int:
    """Crash-restart honesty: a 'verifying' row at boot means the poll loop
    died with the process — mark interrupted, never silently 'verified'."""
    rows = (await db.execute(
        select(BuilderSession).where(
            BuilderSession.status == "verifying"))).scalars().all()
    for bs in rows:
        bs.status = "interrupted"
        bs.log = (bs.log or []) + [{
            "ts": _utcnow(), "kind": "verify",
            "msg": "verify loop lost with process restart — interrupted"}]
    if rows:
        await db.commit()
    return len(rows)


async def list_sessions(db: AsyncSession) -> list[BuilderSession]:
    return (await db.execute(
        select(BuilderSession).order_by(BuilderSession.id.desc())
        .limit(50))).scalars().all()


async def messages(db: AsyncSession, bs_id: int,
                   after_id: int = 0) -> list[BuilderMessage]:
    return (await db.execute(
        select(BuilderMessage)
        .where(BuilderMessage.session_id == bs_id,
               BuilderMessage.id > after_id)
        .order_by(BuilderMessage.id))).scalars().all()
