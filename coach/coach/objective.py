"""CURRENT_OBJECTIVE — deterministic next-step tracker (mini-PTG).

Research basis (CheckMate): an external planner above the LLM lifts long-
horizon success ~20% because the model stops losing the thread between
turns. A full PDDL/graph planner is overkill for curated quests — this
picks ONE concrete next action from facts + open work, deterministically,
zero LLM calls.

Priority (highest first — "open work that already exists" before "go find
something"):
  1. a flag VALUE observed in output but never submitted
  2. a script written but never run, or whose last run failed
  3. a credential found but never tried on any host
  4. the next open checkpoint (authored quests only — blind capstone has
     no checkpoints, falls through to the facts-gap rules below)
  5. open flags + facts gap → recon / enum / cred-attack on the weakest
     known host (never names a solve path — flags carry no authored data)
"""
from __future__ import annotations


def _open_flags(ctx: dict) -> list[dict]:
    return [f for f in ctx.get("flags") or [] if not f.get("solved")]


def _open_checkpoints(ctx: dict, st) -> list[dict]:
    q = ctx.get("quest") or {}
    hit = getattr(st, "checkpoints_hit", set()) or set(
        ctx.get("checkpoints_hit") or [])
    return [c for c in q.get("checkpoints") or []
            if c.get("id") not in hit]


def next_objective(ctx: dict, facts, st) -> tuple[str, str]:
    """(phase, objective-line). Empty objective = nothing actionable."""
    f = facts

    # 1. flag value seen but unsubmitted — the cheapest possible win
    for v, ff in f.flags.items():
        if ff.seen and not ff.submitted:
            return ("objective", (f"submit flag `{v[:48]}` — you already saw "
                                 "it; re-verifying wastes a turn"))

    # 2. script debt: written-never-run beats failed (a failing script at
    #    least ran; an unrun one is pure rewrite-loop risk)
    for fl in f.files.values():
        if fl.kind == "script" and fl.writes and not fl.runs:
            return ("execute", (f"run `{fl.path}` — written {fl.writes}x, "
                               "never executed"))
    for fl in f.files.values():
        if fl.kind == "script" and fl.last_exit not in (None, 0):
            return ("debug", (f"fix `{fl.path}` — last run exited "
                             f"{fl.last_exit}; read the error, don't rewrite "
                             "blind"))

    # 3. creds found but untried — point at a concrete host (untested_creds
    #    have no tried hosts yet, so the first target is the suggestion)
    targets = (ctx.get("quest") or {}).get("targets") or []
    for c in f.untested_creds():
        h = targets[0] if targets else {}
        where = (h.get("name") or (h.get("ip") or "").split("/")[0]
                 or next(iter(f.hosts), "the first host you see"))
        return ("access", (f"try cred `{c.user}/{c.secret}` (from "
                          f"{c.source or 'output'}) on {where} — ssh, smb "
                          "or the service it's for"))

    # 4. authored checkpoints — next one in order
    open_cp = _open_checkpoints(ctx, st)
    if open_cp:
        c = open_cp[0]
        return ("checkpoint", (f"checkpoint `{c.get('name') or c.get('id')}` "
                              "is next — work toward it"))

    # 5. open flags → pick the gap from facts alone (blind-safe: never
    #    reads flag.vm/file_path, only counts observed evidence)
    if _open_flags(ctx):
        unscanned = f.unscanned(targets)
        if unscanned:
            return ("recon", "recon " + ", ".join(unscanned[:3]) +
                    " — no scan evidence yet (nmap -sV baseline)")
        noports = [h for h in f.hosts.values() if h.scans and not h.ports]
        if noports:
            return ("enum", (f"enumerate {noports[0].ip} deeper — scanned "
                            f"{noports[0].scans}x, no services parsed yet; "
                            "try -p- or -sU"))
        # services known, no creds → attack the richest service host
        served = sorted((h for h in f.hosts.values() if h.ports),
                        key=lambda h: -len(h.ports))
        if served and not any(c.valid_on for c in f.creds):
            h = served[0]
            svcs = "/".join(sorted({s.split()[0] for s in
                                    h.ports.values()})[:3])
            return ("foothold", (f"attack {svcs or 'services'} on "
                                f"{h.label()} — no validated cred "
                                "yet"))
        # access exists → grind toward the next open flag
        keys = ", ".join(x.get("key") or "?" for x in _open_flags(ctx)[:3])
        return ("objective", (f"hunt flag(s) {keys} — loot, privesc, "
                             "pivot to hosts without flags yet"))

    return ("", "")


def render(ctx: dict, facts, st) -> str:
    """One-line CURRENT_OBJECTIVE for the context message, or ""."""
    phase, obj = next_objective(ctx, facts, st)
    return f"CURRENT_OBJECTIVE ({phase}): {obj}" if obj else ""
