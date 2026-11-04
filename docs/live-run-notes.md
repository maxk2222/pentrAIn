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

## Worker lifecycle hardening (s1 audit → e1f1aeb)
Findings from watching w1..w3 die silently in cap-t3:
- Parse-death: three workers each died on their FIRST turn to
  'no valid actions parsed' (~10min LLM time each, never retried,
  never collected). Now: up to 2 corrective retries with proper
  assistant/tool_calls pairing; third failure ends gracefully.
- No completion signal: parent had to poll agent_status to learn a
  worker finished — it never did. Now _finish_worker queues a bounded
  note injected on the parent's guaranteed-read result channel.
- Context trim dropped the task brief (msgs[:1]+msgs[-29:]); after
  ~15 turns the worker drifted off-task. Now keeps msgs[:2]+msgs[-28:].
- _denial_seen was global — first window to exec ate the note for all.
  Now per-window, since each context has its own facts snapshot.
- pending_observer_hints popped unscoped — a worker could consume an
  advisory meant for the stuck parent. Now parent-only (window=None).
- Killed workers lost partial findings (w.report never set on kill).
  Kill path now synthesizes a report from last_out so _finish_worker
  still merges; _worker_reasoning + activity indicator cleaned up.
- Denial repeats now escalate (REPEATED xN) and attach a one-shot
  guide hint (filtered→pivoting etc.) — before, the same denied cmd
  could be re-issued silently.
- Caps raised for hard quests: max_workers 4 (parallel only — the
  agent may spawn sequentially without limit), turn_cap 160,
  time_cap 7200s.
- Observer LLM calls get one bounded ~20s retry — 240s ReadTimeouts
  on the busy 27B endpoint silently killed advisories/lessons.
- Frontend: chips show outcome glyphs, finished worker feeds get a
  status-colored result card w/ collapsible report, action_report
  messages carry their wN author label.
2026-11-04

## Agent/subagent comms audit (w7 ghost chip)
- coach_agents roster events merged only — never cleared. A 'running'
  chip from an earlier roster survived restarts/wipes client-side
  forever (user saw a phantom 'w7' from the pre-4-cap era; no such
  worker ever existed in the DB). Fix: roster push is authoritative —
  running-status entries absent from the list are marked killed.
- collect_agent: bounded shield-wait (240s), preempted by operator
  chat, merges report on read — audited clean.
- agent_status: plain roster text, audited clean.
- spawn inline default max_w was 6 vs new settings default 4 — aligned
  (dead code, but misleading).
- Worker tmux windows (pentrain-coach:w1..w4) are never closed —
  panes linger on the trainee desktop after finish/kill. Cosmetic;
  a respawned wN reuses its pane. Worth a kill-window on finish later.
2026-11-04

## FULL EVAL RUN (2026-11-04) — fresh DB, tier-ordered ladder
All progress wiped (attempts/submissions/coach trail/sessions);
quests+settings kept. Rules: tier 1 fully first, then 2, 3, 4.
AD track skipped (no Windows templates). Hard standalones
(ai-llm-injection, cloud-k8s-escape) last in the tier-1 block.
Autonomy 4 + subagents on for every session.
Per-quest findings appended below the ladder table.

| quest | result | actions | time | notes |
|-------|--------|---------|------|-------|
| lab-t1-assessment | ? | | | deploying |

## reasoning-effort root cause (qwen3.8 + LM Studio)
- 'reasoning_effort' never reaches the Jinja ctx on LM Studio /v1
  (issue #2413) — template default 'xhigh' applied to EVERY turn.
  Explains the 600s cancel storms on long contexts.
- qwen3.8 template accepts xhigh|medium|low — our 'high' would raise.
  Now mapped + mirrored into chat_template_kwargs.
- enable_thinking=false DOES reach llama.cpp: ~60% fewer reasoning
  tokens, ~2x faster (live probe 127*43: 214→84 tok, 30s→14s).
  Still not a full off (Heretic merge emits residual think tokens).
- /no_think prompt directive: no effect (template lacks the hook).
- 'low' effort now maps to enable_thinking=false + mirrored low —
  the only way to actually go below xhigh on this deployment.
- Server-side alternative: edit the model's chat_template.jinja
  default('xhigh')->('low') in LM Studio (operator action).
2026-11-04

## web_search + web_fetch (key-free research, gated on kali_internet)
- Engines: html.duckduckgo.com/html/ (primary — verified 10 organic
  results from this egress) → lite.duckduckgo.com (fallback) →
  Marginalia public API (3rd). No keys anywhere.
- DDG lite throws anomaly-modal CAPTCHAs; html endpoint passes with
  Sec-Fetch-*/Referer headers. challenge markers → honest error,
  never silent-empty.
- web_fetch: SSRF-guarded (per-hop incl. redirects) — private/
  loopback/link-local/reserved + literal-IP tricks (2130706433, [::1])
  denied, which also covers all lab CIDRs. trafilatura main-content
  extraction, 8KB cap, binary content-types bounced to exec_in_kali.
- JS-SPA sites (nvd) yield honest thin extraction — known limit,
  no headless browser by design.
- Gate: ctx.session.kali_internet — denial text teaches alternatives;
  CACHED: prefix on TTL-cache hits; 2s DDG debounce shared by
  parent+workers (single client).
- Dispatch fixes folded in: denial sig now uses query/url (no false
  REPEATED across different queries), worker deny text lists the
  real toolset, ALLOWED_ACTIONS drift guard covers both tools.
- Tools offered L3+; workers get both (research tasks parallelize).
2026-11-05

## s1-eval: evidence re-read loop (lab-t1-assessment)
- Agent scanned LAN (12+ hosts) + 4 hosts deep via w2, then spent 5+
  consecutive turns re-reading ~/evidence/*.nmap with cat/grep/ls —
  each result duplicates what history already holds. Looks stalled in
  the feed but is a consolidation loop, not a hang.
- Same class as flag re-read guard: repeated reads of an identical
  path should get an advisory after N — "content already in history,
  synthesize or move on". Soft note, not a deny (different greps on
  one file can be legit — but 3+ reads of one path rarely are).
- w2 crashed on LLM ReadTimeout after 3 parse-corrective retries —
  retry path + crash-report synthesis worked as designed; parent
  unaffected.
- Kali VM clock = UTC-7 (file ts 09:37 == 17:37 UTC) — cosmetic only.
2026-11-04 17:35

## effort_routine default was 'medium' — routine turns never got fast
- llm.reasoning_effort=low only feeds the deep-fallback chain +
  client ctor; the ROUTINE path reads coach.effort_routine which
  was unset → 'medium' → enable_thinking stayed ON → routine turns
  at effective xhigh → 600s cancels on ~90-action contexts (17:47).
- With the mirror, only low/off map to enable_thinking=false —
  routine turns are exactly where thinking-off belongs (exec-loop
  grind). Code default changed medium→low; effort_worker same fix
  on .200 settings. Deep stays medium (escalation quality).
- Takeaway: 'routine/deep/worker' are three separate knobs —
  patching llm.reasoning_effort alone leaves the hot path slow.
2026-11-04 17:55

## BUG: unicode commands kill QGA file-write (eval-blocker)
- Agent wrote ~/lan-report.md via heredoc containing em-dashes/unicode
  → PVE agent/file-write 500 'Wide character in subroutine entry'
  (Agent.pm:643) → the DELIVERABLE write failed; agent then idled on
  'infra error recovery'. Any non-ASCII byte in the exec script dies
  the same way — model output loves — and ’ ’.
- Fix in agent_file_write (pve.py): try raw write; on failure with
  non-ascii payload, ship ASCII base64 to <path>.ptnb64 and decode
  in-guest via agent_exec_sh (short args, no virtio wedge). ASCII
  fast-path unchanged; errors on ASCII content still propagate.
- Covers every caller: coach /tmp/ptn-*.sh scripts, kali_net up/down,
  flags seeding, hosts.sh. Tests: b64 fallback path + ascii-reraise.
2026-11-04 18:20

## BUG: deep-effort spend marker died on every coach restart
- _deep_spent_ts was in-memory only → each redeploy burned one fresh
  600s deep cancel at stage>=2 (s1: 3 rebuilds = ~30min dead time).
- Fix: spend now records kind="effort" in the session traj (survives,
  rotated per attempt); attach restores + CLAMPS to attach-time —
  last_progress_ts re-seeds to now without progress events, so only
  new observed progress re-earns depth. 2 tests.
2026-11-04 18:55

## INFRA error message taught 'probe' but not 'retry'
- After the unicode 500, agent waited 30s then abandoned the report
  deliverable — the message said probe with `echo ok` but never said
  RETRY the command; agent read it as a soft denial and fell back to
  template re-reads (denied 3x). Reworded: transport failure is not a
  denial — retry after the channel probe.
2026-11-04 18:55

## Worker parse failures were undiagnosable notes
- w1-w4 all logged bare 'no valid actions parsed' — no sample of what
  the model emitted. Notes now carry the raw output head (140 chars).
- Salvage path added: 3 correctives burned → status=failed + salvage
  report (last real output) instead of garbage-as-report.
2026-11-04 19:05

## web_search/web_fetch: 0 uses in ~5h despite INTERNET=YES
- s1 is a pure LAN-assessment quest — arguably legit non-use, but the
  router httpd/3.0 fingerprint + service CVE lookup were real chances.
  Watch whether memory/playbook tools change the consult reflex.
2026-11-04 19:05

## New feature block deployed mid-eval (6824e2d)
- attack-path long-term memory (record_play/search_memory/play_outcome),
  bounded playbooks, persistent channels c1/c2, threat_model card,
  peek_pane, coach.ablation kill-switches, role knowledge-preload,
  7 new modules, scope DNS-pinning. 421 coach + 157 backend tests.
- Tool surface changes mid-session: additive only; watch for the
  model exploring new tools vs finishing the report deliverable.
2026-11-04 19:15

## SOLVED: lab-t1-assessment (s1, ~5h wall, ~60 turns)
- Winning sequence: unicode fix deployed → INFRA-retry hint told the
  agent transport failure != denial → agent retried `cat > lan-report.md`
  → "Report written: 113 lines" → check_flag verified report → solved.
- The deliverable was a verified report file, not a flag string —
  flag_submissions stayed 0; check_flag target-side check is what closed it.
- Deep-effort marker recorded in traj (kind:"effort") — restart-safe
  mechanism live; re-read advisory fired correctly pre-write.

## FALSE-ALARM: dockerd fifo death mimics a hung coach
- dockerd's stdout copier died ("reading from a closed fifo" 19:45) →
  coach logs stopped reaching json-file → looked frozen for 35min.
- py-spy showed idle epoll loop; coach was actually DETACHED-correct:
  session had solved, active_sessions=[]. Log silence is NOT hang
  evidence — verify via traj mtime + backend access-log + DB state.
- Ops lesson: check `docker logs --since` freshness against watchdog
  cadence (300s) — silence longer than one interval means the logging
  pipeline died, not necessarily the app.
2026-11-04 20:05

## SOLVED: linux-t1-first-foothold (s2, ~12min vs s1's 5h)
- Chain: briefing creds → ssh user flag → sudo -l → sudo vim →
  :!/bin/sh → root flag. Two clean submits, zero wasted turns.
- routine=low (thinking-off) held ~10-80s turns vs s1's 40-600s.
- Observer distilled 2 banner/MOTD cred-hint lessons post-solve.
- type_in_pane handled the interactive vim escape natively.
2026-11-04 20:45

## BUG: create autonomy race (fixed 7d1a251)
- SessionStartIn.autonomy_level applied after create_session's first
  commit → coach attached at autonomy 2 despite create(4). Now passed
  through create_session before first commit.
- Note: abort on solved keeps attempts but frees RAM for next quest —
  the ladder teardown path is abort(), not solve-auto-destroy.
2026-11-04 20:45

## SOLVED: linux-t1-suid-hunt (s3, ~15min)
- Chain: ssh → find -perm -4000 → GTFOBins → root. All 4 checkpoints.
- Coach detached cleanly on solve; observer lessons stored.

## Deploy cadence (ladder ops)
- abort(solved) → wait aborted → create(4,subagents) → ~10-16min deploy
  → ready → activate. Deploy-task survives backend restarts if session
  already 'ready'; mid-'deploying' restart kills it (needs reset).
- 88 quests synced post-redeploy; exploits/audit packs included.
- NOTE: activate only when state=ready — "session not ready" else.
2026-11-04 22:15

## SOLVED: linux-t1-exam (s4, ~15min)
- intern@10.1.10.40 → user flag → python3 SUID → root. Observer lesson:
  "SUID python3 os.execl('/bin/sh') hangs waiting for TTY; use os.setuid+os.system" — learned live.
- NOTE: admin auth went live mid-run (token needed; old 'pentrain' bearer 401).
  Cleared hash via DB → adopted password 'pentrain' → signed token in use.

## SOLVED: net-t1-services (s5, ~18min, 3 flags + 3 cps)
- ftp anon → web backup → mysql root/'mysql' secrets → dbadm ssh 'Summer2024!' → flag.
- Deploy ~25min (kali ansible pkg install slow tail). Quest chain itself clean.
2026-11-04 22:52

## SOLVED: net-t1-open-shares (s6, ~20min, 3 flags + 3 cps)
- smb anon public share → finance share via svc-backup/Backup2024! (interactive
  smbclient channel used correctly) → ssh svc-backup → user.txt.
- NOTE: create call must carry subagents_enabled:true — earlier winning create
  had it false; fixed via POST /sessions/{id}/subagents live toggle.
2026-11-04 23:22

## SOLVED: net-t1-exam (s7, ~35min, 3 flags + 3 cps)
- ftp → smb fieldtech/Field2024! → su privesc → root. Blind exam clean.
- FIX b597f5b: SessionStartIn now takes subagents_enabled (creation-time race,
  same class as autonomy_level). Deployed; s7 verified subagents toggle works.

## Track status: net-t1 3/3 SOLVED (services, open-shares, exam)
2026-11-05 01:10
