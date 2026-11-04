#!/usr/bin/env python3
"""agent_eval — run a blind full-auto (L4) session and report the outcome.

Designed for capstone/benchmark quests (cap-t3-nordwind): the coach gets no
hints, no checkpoints, no operator message — only the quest briefing. The
script bumps the guardrail budgets for the run (action_budget / daily token
budget) and restores them afterwards.

Usage:
    python scripts/agent_eval.py --quest cap-t3-nordwind \
        --base http://127.0.0.1:8000 --password <admin> [--out report.md]

Stdlib only — no third-party deps.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request

TERMINAL = {"solved", "aborted", "failed"}


def api(base: str, token: str | None, method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"api {method} {path} -> {e.code}: {e.read()[:300]!r}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"api {method} {path} -> {e}") from e


def fmt_ts() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quest", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--password", required=True, help="admin password (auth/login)")
    ap.add_argument("--autonomy", type=int, default=4)
    ap.add_argument("--no-subagents", action="store_true")
    ap.add_argument("--ablation", default="",
                    help="comma list of subsystems to disable for ablation "
                         "runs: ptg,roles,coverage,memory")
    ap.add_argument("--action-budget", type=int, default=300)
    ap.add_argument("--token-budget", type=int, default=0,
                    help="llm.daily_token_budget during the run (0 = unlimited)")
    ap.add_argument("--deploy-timeout-min", type=int, default=45)
    ap.add_argument("--timeout-min", type=int, default=240)
    ap.add_argument("--poll-s", type=int, default=15)
    ap.add_argument("--out", help="also write the report here (markdown)")
    args = ap.parse_args()

    token = api(args.base, None, "POST", "/api/auth/login",
                {"password": args.password})["token"]
    print(f"[{fmt_ts()}] logged in")

    # bump guardrail budgets for the run; restore afterwards
    old = api(args.base, token, "GET", "/api/settings")
    api(args.base, token, "PATCH", "/api/settings", {"updates": {
        "coach.action_budget": args.action_budget,
        "llm.daily_token_budget": args.token_budget,
        "coach.ablation": args.ablation,
    }})
    print(f"[{fmt_ts()}] budgets: action_budget={args.action_budget} "
          f"token_budget={args.token_budget}"
          + (f" ablation={args.ablation}" if args.ablation else ""))

    sid = None
    deploy_s = run_s = 0
    try:
        s = api(args.base, token, "POST", "/api/sessions",
                {"quest_id": args.quest})
        sid = s["id"]
        print(f"[{fmt_ts()}] session {sid} deploying "
              f"(timeout {args.deploy_timeout_min}m)…")
        deploy_t0 = time.time()
        while s["state"] != "ready" and s["state"] not in TERMINAL:
            if time.time() - deploy_t0 > args.deploy_timeout_min * 60:
                raise SystemExit("deploy timeout — check /log endpoint")
            time.sleep(args.poll_s)
            s = api(args.base, token, "GET", f"/api/sessions/{sid}")
        if s["state"] != "ready":
            tail = api(args.base, token, "GET", f"/api/sessions/{sid}/log")
            print(f"session {s['state']}: {s.get('error')}\n"
                  f"--- deploy log tail ---\n{(tail or {}).get('log', '')[-2000:]}")
            return 1
        deploy_s = int(time.time() - deploy_t0)
        print(f"[{fmt_ts()}] ready in {deploy_s}s")

        if not args.no_subagents:
            api(args.base, token, "POST", f"/api/sessions/{sid}/subagents",
                {"enabled": True})
        api(args.base, token, "POST", f"/api/sessions/{sid}/autonomy",
            {"level": args.autonomy})
        api(args.base, token, "POST", f"/api/sessions/{sid}/activate")
        print(f"[{fmt_ts()}] active — agent loop running "
              f"(L{args.autonomy}, subagents={not args.no_subagents})")

        run_t0 = time.time()
        prev_solved: set[str] = set()
        flag_ts: dict[str, str] = {}
        while s["state"] not in TERMINAL:
            time.sleep(args.poll_s)
            s = api(args.base, token, "GET", f"/api/sessions/{sid}")
            flags = api(args.base, token, "GET", f"/api/sessions/{sid}/flags")
            solved = {f["key"] for f in flags["flags"] if f["solved"]}
            for k in sorted(solved - prev_solved):
                flag_ts[k] = fmt_ts()
                print(f"[{fmt_ts()}] flag solved: {k} "
                      f"({len(solved)}/{flags['total']})")
            prev_solved = solved
            if time.time() - run_t0 > args.timeout_min * 60:
                print(f"[{fmt_ts()}] run timeout — aborting session")
                api(args.base, token, "POST", f"/api/sessions/{sid}/abort")
                s = api(args.base, token, "GET", f"/api/sessions/{sid}")
                break
        run_s = int(time.time() - run_t0)
    finally:
        api(args.base, token, "PATCH", "/api/settings", {"updates": {
            "coach.action_budget": old.get("coach.action_budget", 50),
            "llm.daily_token_budget":
                old.get("llm.daily_token_budget", 2_000_000),
            "coach.ablation": old.get("coach.ablation", ""),
        }})

    flags = api(args.base, token, "GET", f"/api/sessions/{sid}/flags")
    usage = api(args.base, token, "GET", "/api/llm/usage?days=1")
    am = api(args.base, token, "GET", f"/api/sessions/{sid}/agent-metrics")
    lb = api(args.base, token, "GET", f"/api/quests/{args.quest}/leaderboard")
    attempt = next((a for a in (lb.get("history") or [])
                    if a.get("session_id") == sid),
                   lb.get("best") if (lb.get("best") or {}).get("session_id") == sid
                   else None)

    lines = [
        f"# agent eval — {args.quest} (session {sid})",
        "",
        f"- final state: **{s['state']}**",
        f"- autonomy: L{args.autonomy}"
        + ("" if args.no_subagents else " + subagents"),
        f"- deploy time: {deploy_s}s · run time: {run_s}s",
        f"- flags: {flags['solved']}/{flags['total']}",
        *([(f"- score: {attempt['score']} (attempt #{attempt['id']}, "
            f"{attempt.get('flags_found', '?')} flags, "
            f"{attempt.get('duration_s', '?')}s)")] if attempt else []),
        "",
        "| flag | name | points | solved | first seen |",
        "|---|---|---|---|---|",
    ]
    for f in flags["flags"]:
        lines.append(f"| {f['key']} | {f['name']} | {f['points']} | "
                     f"{'yes' if f['solved'] else 'no'} | "
                     f"{flag_ts.get(f['key'], '—')} |")
    if am:
        # agent-behavior metrics — the "where exactly did it break" view:
        # denied reasons surface guard-triggering (foreign ips, rewrite
        # loops), hallucination counters surface grounding failures
        tools = " · ".join(f"{k}x{v}" for k, v in am["tool_counts"].items())
        hal = am["hallucination"]
        fl = am["flags"]
        deny_head = "; ".join(
            f"{r} x{n}" for r, n in
            list(am["denied"]["reasons"].items())[:4])
        lines += [
            "",
            "## agent metrics",
            "",
            (f"- actions: {am['actions_total']} in {am['span_s']:.0f}s "
             f"({tools})"),
            f"- exec ok/error: {am['exec']['ok']}/{am['exec']['error']}",
            f"- denied: {am['denied']['total']}"
            + (f" ({deny_head})" if deny_head else ""),
            (f"- grounding: foreign-ip denies {hal['foreign_ip_denials']}, "
             f"unverified submits {hal['unverified_flag_submits']}, "
             f"rejected submits {hal['rejected_flag_submits']}"),
            (f"- first flag: {fl['first_flag_key']} after "
             f"{fl['time_to_first_flag_s']}s"
             if fl.get('first_flag_key') else "- first flag: none"),
            (f"- llm: {am['llm']['calls']} calls, "
             f"{am['llm']['total_tokens']} tokens"),
        ]
        # P3 engagement/orchestration metrics — the "did it coordinate"
        # view: foothold time, coverage pct, findings states, worker
        # utilization and parent↔worker overlap
        eng = am.get("engagement") or {}
        orch = am.get("orchestration") or {}
        mem = am.get("memory") or {}
        cov = eng.get("coverage") or {}
        if eng or orch:
            lines += ["", "## engagement metrics", ""]
            if eng.get("time_to_foothold_s") is not None:
                lines.append(
                    f"- time to foothold: {eng['time_to_foothold_s']}s")
            if eng.get("time_to_first_confirmed_s") is not None:
                lines.append(
                    f"- first confirmed finding: "
                    f"{eng['time_to_first_confirmed_s']}s")
            if cov.get("surfaces"):
                lines.append(
                    f"- coverage: {cov.get('settled')}/{cov.get('surfaces')} "
                    f"surfaces settled ({cov.get('pct')}%) "
                    f"by-outcome={cov.get('by_outcome')}")
            if eng.get("findings"):
                lines.append(f"- findings: {eng['findings']}"
                             + (" report built" if eng.get("report_built")
                                else ""))
            if eng.get("scope_denials"):
                lines.append(f"- scope denials: {eng['scope_denials']}")
            if orch.get("worker_spawns"):
                lines.append(
                    f"- workers: {orch['worker_spawns']} spawns, "
                    f"{orch.get('worker_execs')} execs "
                    f"(util {orch.get('worker_util_pct')}%), "
                    f"parent-worker overlap {orch.get('recon_overlap_execs')} "
                    "execs")
            if any(mem.values()):
                lines.append(
                    f"- memory: {mem.get('search')} searches, "
                    f"{mem.get('recorded')} plays recorded, "
                    f"{mem.get('feedback')} feedback")
            if am.get("playbooks"):
                lines.append(f"- playbooks: {am['playbooks']}")
    if usage:
        lines += ["", "## LLM usage (last 24h)", "",
                  "```json", json.dumps(usage, indent=2)[:2000], "```"]
    report = "\n".join(lines)
    print("\n" + report)
    if args.out:
        import pathlib
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(report + "\n")
        print(f"\nwrote {args.out}")
    return 0 if s["state"] == "solved" else 1


if __name__ == "__main__":
    sys.exit(main())
