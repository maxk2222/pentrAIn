# ADR-0003: Coach autonomy model

## Status
Accepted

## Context
The coach must be able to act on the Kali box "in emergencies" (user requirement) while staying a teacher, not an autopilot. Unconstrained agent execution is both a safety and a pedagogy problem.

## Decision
Four per-session autonomy levels, selectable in Settings and overridable per session:

1. **Spectate** — silent observation; analysis goes to the coach log only.
2. **Advisor** (default) — proactive nudges on stuck-detection, hint offers, Q&A.
3. **Copilot** — concrete command suggestions rendered as "run on Kali" chips; each executed only on explicit user confirm.
4. **Takeover** — may execute autonomously via the engine-PVE `agent/exec` channel; commands are typed into a visible `tmux` coach terminal on the Kali desktop and mirrored in a UI action feed.

Guardrails: exec tool exists only for the session's Kali VMID (no host/hypervisor exec), destructive-command denylist, per-session action budget, kill switch, complete `CoachAction` audit.

## Consequences
- Takeover is powerful but observable and reversible (quest VMs are disposable + snapshot-reset).
- Level state rides with the session record; coach cannot raise its own level.
