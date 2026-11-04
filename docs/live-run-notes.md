# Live-Run Observations

Findings from live quest runs (s84+). Each entry: behavior observed →
generalized fix applied or candidate noted. Secrets/flags are NOT recorded.

## s84 cap-t3-nordwind (reset → fresh run, 2026-11-03/04)

### Fixed live
- `rollback_all` left all range VMs stopped → "ready" session, dead range.
  Fix: post-rollback vm_start + parallel QGA wait (e7fd9ab)
- `agent_file_read` returned non-b64 garbage on this PVE build → screenshot
  path silently corrupt. Fix: read via agent_exec+base64 (e7fd9ab)
- coach re-attached during `resetting` → exec'd against rolling-back VMs.
  Fix: start() refuses resetting/aborting (4078b7a)
- observer re-consumed pre-reset traj → stale advisory on clean run.
  Fix: traj.rotate() + observer.drop() on resetting (9294d99)
- `missing:tool@host` fired on the tool as PAYLOAD (`scp /usr/bin/sshpass
  u@h:` = the fix, not a use). Fix: command-position match (916e772)
- `filtered:ip@kali` fired on remote-vantage connects: segment heads were
  joined across `;` splits that broke inside quotes — a python urllib
  call ON web01 to app01 got denied as kali-local. Fix: per-segment eval
  + quote-aware splitter, both verified (13804f7)
- /api/coach/config never propagated `observer_*` keys → observer settings
  were dead config. Fixed in config endpoint (f1cde4f)

### Behavior notes
- Adaptive effort works: routine turns ~25-50s vs prior 600s cancels;
  stage-2 deep turns still occasionally hit the 600s cap (1× in 70min —
  acceptable, that's the intended quality/latency trade-off)
- stuck_s counts fact-growth only — during long extraction phases
  (git object archaeology) the reflector escalates to stage-2 despite
  real intellectual progress. Candidate: feed output-novelty (the dedup
  signal already exists) into the stuck metric so productive-but-slow
  phases don't burn deep-effort nudges
- Observer advisory was point-accurate (wget -r .git mirror tip mid
  per-object-curl) but not adopted — agent kept its working-but-slower
  path. Acceptable: advisory, not command.
- cred spray guard untested this run — first cred use came from the
  git-extracted deploy cred straight into the right host
- reread/dedup guards fired correctly on stale-habit reads
  (/tmp/nmap_out.txt never existed in this run)
- `ssh: Could not resolve hostname web01` — agent used the Kali-side
  alias INSIDE a remote shell on web01 (hosts don't know their own
  alias). Self-corrected on next turn via output. Candidate guide note:
  remote tails always resolve IPs, never local aliases.
- Observer advisories get sanitize_lesson_text applied — "use the shared
  <redacted> from git history" loses the literal but keeps the pointer.
  Acceptable: agent owns the material (extracted it), tip supplies the
  move. Keeps the no-loot-in-texts invariant for all observer output.
- Observer live-facts integration works: advisory referenced the
  config.yml secret found via git archaeology — grounded, not generic.
- Observer advisory quality gap (04:22): suggested "ssh web01→app01 with
  deploy cred" AFTER that exact attempt already failed with Permission
  denied — either the nested-ssh auth failure never became a settled
  fact (percept doesn't capture auth-fails inside remote tails?) or the
  advisory prompt didn't surface it. Candidate: verify percept records
  `denied:ssh-user@host` for nested pivots, not only direct ssh.
- /dev/tcp probing is a genuinely good minimal-host fallback the agent
  discovered itself (bash builtin, no nmap/curl needed) — worth a guide
  module mention if not already present.

### Incident: platform down + DB loss (2026-11-04 ~05:45)
- The whole pentrain compose stack vanished mid-run (containers removed,
  named volumes incl. pentrain-data gone; pentrain-traj deleted). Cause
  unknown — no daemon restart (other projects' uptime intact), so an
  explicit `compose down -v` or equivalent.
- s84 progress (flag-1, ~450 actions), all session history, observer
  lessons in DB, and the traj volume were lost unrecoverably.
- Restore path exercised: `docker compose -f engine/docker-compose.yml
  build && up -d` (images were stale — hot-patches had lived only in
  running containers; rebuild from git was required).
- DB re-seeded itself (61 quests, 11 tracks). All runtime config lives in
  the `settings` table — had to be restored from history:
  engine.* (mode=direct, pve url/node/token, ludus url/key,
  testing_allow, kali_wan_bridge), llm.* (base_url, model, vision_model,
  reasoning, effort, budget), platform.api_url, setup.completed,
  security.admin_token_hash. coach.*/resources.* left at defaults —
  s84 behavior matched them anyway.
- Missing platform feature (candidate): settings export/backup —
  a wiped DB currently loses ALL config; a `GET /api/settings/export`
  + import-on-boot would make restores one-step.
- Orphaned nordwind range (VMs 102-106) still ran on PVE and held host
  RAM → new session create failed the live resource gate (4G free).
  destroy_range via engine freed it — range teardown is required
  cleanup after a stack wipe.
- Fresh DB ⇒ tier gates active again. Seeded one Attempt row per track
  tier below the test targets (synthetic solves: cap-t2, web/net/wifi/
  for/scr/linux-t2, ad-t1+t2) so the ladder is open; real solves
  accumulate for the exams.

## s1 cap-t3-nordwind (rebuilt stack, 2026-11-04)
- flag-1 in ~45min (vs ~90min on s84) — recon immediately parallelized
  via spawn_agent x3; guide modules pulled proactively.
- Candidate: lookup_guide re-fetch dedup — same module pulled 5x in
  ~18min (~5x module tokens wasted). Soft note "already loaded" after
  the 2nd fetch of a module name per session.
- Candidate: worker efficiency — a spawned nmap -p- worker held its
  slot 5628s for ONE action; workers need their own time-bound
  heuristics (or the spawn brief should prefer bounded scans). Also:
  main agent re-ran the same app01 scan itself while w2 covered it —
  spawn-then-duplicate pattern wastes actions.
- Recurring papercut: `sshpass` interactive prompts repeatedly leave
  the shared pane busy; C-c recovers but costs turns. Agent later
  self-solved with `timeout 15 sshpass ...`. Still worth a guide note.
- Adaptive-effort design hole: `coach.effort_deep=""` falls back to
  llm.reasoning_effort=high — but during long extraction grinds stage-2
  becomes the DEFAULT state, so every turn ran high → 3x 600s cancels
  in 30min (~33min wall-clock lost). Live-mitigated via
  coach.effort_deep=medium. Candidate: cap consecutive deep-effort
  turns at stage-2 (e.g. first N escalations deep, then medium until
  progress resets) instead of a flat effort.
- Observer lesson LLM calls occasionally ReadTimeout at 240s — big
  analysis prompt on the 27B. Advisory-only, tolerable; monitor.
- stuck_s carries deploy/ready idle time into the run — session
  entered at stage-2 immediately after activation. Fixed: resync()
  now folds started_at/ready_at into the progress clock (forward only).

### Optimization masterplan → implemented (2026-11-04)
All generalized fixes from the s1 findings above, landed + tested:
- lookup_guide dedup: per-window, keyed on the RESOLVED module id —
  repeat pulls return "already loaded" instead of re-paying the body.
- Deep-effort decay: stage>=2 spends one deep turn per no-progress
  window (`_deep_spent_ts` marker); a cancelled deep leaves it spent.
  Progress re-earns depth — quality kept for real escalation moments.
- resync() progress-clock seeding (started_at/ready_at, forward-only).
- Probe-verb exemption in missing: denials — `which`/`whereis`/
  `type`/`hash`/`command -v` args are stripped before invocation-match
  (`which expect python3 perl` no longer dies on missing:expect).
- Literal-var note: `sshpass -p '$var'` results now name the single-
  quote footgun instead of letting the auth failure look cred-related.
- Worker-dup advisory: main-window execs on a running worker's target
  get a once-per-pair collect_agent hint (advisory, never denies).
- Observer LLM: dedicated client now runs reasoning=False — inherited
  reasoning=high let distillation calls burn the 240s cap
  (ReadTimeout on advisory AND lesson paths).
- Advisory prompt rule: FACTS dead ends (missing:/denied:/filtered:/
  blocked:) must not be re-proposed — stale tips observed live.
- pivoting.md: own-alias resolution note, `timeout 15` sshpass wrap.
- spawn_agent reply nudges bounded tasks (top-ports over -p-).
- NEW FEATURE: GET /api/settings/export (unredacted, admin-gated) +
  POST /api/settings/import — one-step restore for the next stack
  wipe; import reuses PATCH coercion + CLIENT_KEYS rebuild.

## Ladder queue
web-t3, net-t3, wifi-t3, for-t3, scr-t3, linux-t3, lab-t1, T3-exams,
cap-t4-cloudburst; AD track blocked on windows templates (packer).
Restarted: cap-t3-nordwind as session 1 on the rebuilt stack.
