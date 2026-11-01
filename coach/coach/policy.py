"""Policy: when (and whether) the coach may speak/suggest/act.

Design rule: SILENCE IS THE DEFAULT. The coach may only break it when the
trainee is genuinely stuck, drifting, or idle too long — and it backs off
when proactive messages don't produce progress.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .state import SessionState

# verbosity → how eagerly the coach may initiate contact (scales all thresholds)
VERBOSITY_GAP = {"terse": 1.6, "normal": 1.0, "verbose": 0.7}
# after this many proactive messages without progress, shut up harder
MAX_STREAK = 3


@dataclass
class PolicyDecision:
    may_proactive: bool     # may send unsolicited message
    reason: str = ""
    urgency: str = "low"    # low|medium|high — biases prompt tone
    stage: int = 0          # escalation depth: 0 soft nudge, 1 direction, 2 explicit pointer


class Policy:
    def __init__(self, escalation: dict, *, nudge_s: int, hint_s: int,
                 verbosity: str = "normal", takeover_pace_s: int = 10):
        self.gap_factor = VERBOSITY_GAP.get(verbosity, 1.0)
        # verbosity scales the stuck thresholds too — terse coaches tolerate
        # longer silence before speaking at all
        self.observe_grace_s = int(escalation.get("observe_grace_s", 180))
        self.nudge_s = int(escalation.get("nudge_s", nudge_s) * self.gap_factor)
        self.hint_s = int(escalation.get("hint_s", hint_s) * self.gap_factor)
        self.takeover_pace_s = takeover_pace_s

    def evaluate(self, st: SessionState, now: float | None = None) -> PolicyDecision:
        now = now or time.time()
        if not st.coach_enabled:
            return PolicyDecision(False, "coach disabled")
        # proactive messaging only while the trainee is actually working
        if st.state != "active":
            return PolicyDecision(False, f"session {st.state}")
        if st.autonomy_level <= 1:
            return PolicyDecision(False, "spectate mode")

        stuck = st.stuck_s(now)
        idle = st.idle_s(now)
        since_nudge = now - st.last_nudge_ts

        # escalation depth = how long stuck, deepened by ignored nudges —
        # each unanswered proactive message should become MORE specific
        stage = min(2, max(
            (stuck > self.nudge_s) + (stuck > self.hint_s),
            st.proactive_streak,
        ))

        # backoff: streak of proactive msgs without any progress → long silence
        if st.proactive_streak >= MAX_STREAK:
            backoff = self.hint_s * 2
            if since_nudge < backoff:
                return PolicyDecision(False, f"backing off ({int(backoff - since_nudge)}s left)")

        # never spam: minimum gap between proactive messages (verbosity-scaled)
        min_gap = max(self.observe_grace_s, 300) * self.gap_factor
        # takeover is an agent loop — the coach IS the worker; the in-turn
        # chain carries the actual work, so the gap only paces how quickly a
        # NEW chain may start after the model paused (~10s settle, not 90s)
        if st.autonomy_level >= 4:
            min_gap = min(min_gap, self.takeover_pace_s)
        if since_nudge < min_gap:
            return PolicyDecision(False, f"nudge cooldown ({int(min_gap - since_nudge)}s left)")

        if st.autonomy_level >= 4:
            # full-auto: idle/stuck gates assume a trainee who must start on
            # their own — at takeover the coach IS the trainee, so work right
            # away instead of waiting for a stuck threshold that never fits
            return PolicyDecision(True, "takeover loop", "high", stage)

        if stuck > self.hint_s:
            return PolicyDecision(True, f"stuck {int(stuck)}s > hint_s", "high", stage)
        if stuck > self.nudge_s and idle < self.nudge_s:
            return PolicyDecision(True, f"stuck {int(stuck)}s, still working", "medium", stage)
        if idle > self.nudge_s:
            return PolicyDecision(True, f"idle {int(idle)}s — may be lost", "medium", stage)
        return PolicyDecision(False, "within grace")
