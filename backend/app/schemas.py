"""Pydantic API schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class LoginIn(BaseModel):
    password: str


class TokenOut(BaseModel):
    token: str


class TrackOut(BaseModel):
    slug: str
    title: str
    description: str
    icon: str
    order: int
    quest_count: int = 0
    solved_count: int = 0
    level: int = 1


class FlagOut(BaseModel):
    key: str
    name: str
    kind: str
    points: int
    solved: bool = False


class QuestOut(BaseModel):
    id: str
    track_slug: str
    tier: int
    title: str
    summary: str
    requirements: dict
    scoring: dict
    locked: bool = False
    lock_reason: str = ""
    solved: bool = False
    best_score: int | None = None
    exam: bool = False


class QuestDetailOut(QuestOut):
    briefing_md: str
    defense_md: str
    cheatsheet_md: str = ""
    track_cheatsheet_md: str = ""
    topology: dict = Field(default_factory=dict)
    hints: list[dict]
    flags: list[FlagOut]


class SessionFlagsOut(BaseModel):
    flags: list[FlagOut]
    solved: int
    total: int


class SessionOut(BaseModel):
    id: int
    quest_id: str
    state: str
    kali_vmid: int | None
    autonomy_level: int
    coach_enabled: bool
    kali_internet: bool = False
    kali_wan_ip: str | None = None
    subagents_enabled: bool = False
    created_at: str | None
    ready_at: str | None
    error: str | None = None


class InternetIn(BaseModel):
    enabled: bool


class AutonomyIn(BaseModel):
    level: int = Field(ge=1, le=4)


class SubagentsIn(BaseModel):
    enabled: bool


class CoachEnabledIn(BaseModel):
    enabled: bool


class SessionStartIn(BaseModel):
    quest_id: str
    autonomy_level: int | None = Field(default=None, ge=1, le=4)


class FlagSubmitIn(BaseModel):
    value: str


class FlagSubmitOut(BaseModel):
    correct: bool
    flag_key: str | None
    points: int
    all_solved: bool
    solved: list[str]
    total: int
    detail: str | None = None   # e.g. "condition 2 of 3 failed"


class HintUseIn(BaseModel):
    hint_id: str


class AssistIn(BaseModel):
    """UI aid the trainee opted into — leaderboard 'solve style'."""
    kind: str = Field(pattern="^(sheet|chat)$")


class ResetIn(BaseModel):
    hard: bool = False


class ConfirmActionIn(BaseModel):
    accept: bool


class FlagCheckIn(BaseModel):
    flag_key: str = Field(min_length=1, max_length=64)


class AttemptOut(BaseModel):
    id: int
    quest_id: str
    session_id: int
    score: int
    flags_found: int
    flags_total: int
    hints_used: int
    coach_interventions: int
    assistance: dict = Field(default_factory=dict)
    breakdown: dict = Field(default_factory=dict)
    duration_s: int
    created_at: str | None


class LeaderboardOut(BaseModel):
    best: AttemptOut | None
    history: list[AttemptOut]


class SettingsPatch(BaseModel):
    updates: dict


class ChatIn(BaseModel):
    content: str


class TelemetryBatchIn(BaseModel):
    token: str
    events: list[dict]


class CoachMessageIn(BaseModel):
    session_id: int
    content: str
    kind: str = "chat"
    meta: dict = Field(default_factory=dict)


class CoachSuggestIn(BaseModel):
    session_id: int
    command: str
    why: str = ""


class CoachStreamIn(BaseModel):
    """Ephemeral streaming draft — relayed to the session WS, never persisted.
    `content` is cumulative (idempotent against reordering). `agent` names
    the producing agent ("main" or a worker id like "w1") so the UI can
    route parallel subagent output into per-agent feeds."""
    session_id: int
    draft_id: str = Field(max_length=64)
    content: str = Field(default="", max_length=4000)
    reasoning: str = Field(default="", max_length=4000)
    done: bool = False
    kind: str = "chat"
    agent: str = Field(default="main", max_length=16)


class CoachActivityIn(BaseModel):
    """Ephemeral 'working' status — the UI shows a live indicator while a
    slow action (exec, screen analysis, flag check) is in flight. `agent`
    separates the indicators of parallel worker agents."""
    session_id: int
    active: bool
    text: str = Field(default="", max_length=200)
    agent: str = Field(default="main", max_length=16)


class CoachAgentState(BaseModel):
    """One worker's roster entry — drives the UI's clickable agent chips."""
    id: str = Field(max_length=16)
    task: str = Field(default="", max_length=500)
    status: str = Field(default="running", max_length=16)
    actions: int = 0
    elapsed: float = 0.0


class CoachAgentsIn(BaseModel):
    """Worker roster snapshot — sticky bus event replayed to late UI
    subscribers so agent chips survive a page reload."""
    session_id: int
    agents: list[CoachAgentState] = Field(default_factory=list, max_length=8)


# tmux window names inside the pentrain-coach session — worker agents run on
# their own window (w1..w3); pattern keeps tmux target syntax safe.
_WINDOW_RE = r"^[a-z0-9][a-z0-9-]{0,14}$"


class CoachExecIn(BaseModel):
    session_id: int
    command: str
    window: str | None = Field(default=None, pattern=_WINDOW_RE)


class CoachTypeIn(BaseModel):
    session_id: int
    text: str
    window: str | None = Field(default=None, pattern=_WINDOW_RE)


class CheckpointIn(BaseModel):
    session_id: int
    checkpoint_id: str


class CoachFlagIn(BaseModel):
    session_id: int
    value: str = Field(max_length=256)


class CoachFlagCheckIn(BaseModel):
    session_id: int
    flag_key: str = Field(max_length=64)


# coach-internal bookkeeping tools that may self-report status=ok — real
# actions (exec_in_kali, submit_flag, …) go through their own endpoints and
# must NEVER be fabricatable through this audit sink
_OK_AUDIT_TOOLS = frozenset({
    "spawn_agent", "collect_agent", "agent_status", "kill_agent",
    "update_plan", "note"})


class CoachActionLogIn(BaseModel):
    """Coach self-reported action audit (guard denials happen coach-side,
    before any backend call — without this they never reach the DB)."""
    session_id: int
    tool: str = Field(max_length=64)
    args: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    status: str = Field(default="denied", pattern="^(denied|error|ok)$")

    @model_validator(mode="after")
    def _ok_only_for_internal_tools(self):
        if self.status == "ok" and self.tool not in _OK_AUDIT_TOOLS:
            raise ValueError(
                f"status=ok audit rows only allowed for internal tools "
                f"{sorted(_OK_AUDIT_TOOLS)} — {self.tool!r} claims a real "
                f"action it can't prove")
        return self


class EngineStatusOut(BaseModel):
    mode: str
    health: dict
    resources: dict
    node: dict | None = None
