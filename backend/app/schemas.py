"""Pydantic API schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


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
    created_at: str | None
    ready_at: str | None
    error: str | None = None


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


class HintUseIn(BaseModel):
    hint_id: str


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
    `content` is cumulative (idempotent against reordering)."""
    session_id: int
    draft_id: str = Field(max_length=64)
    content: str = Field(default="", max_length=4000)
    done: bool = False
    kind: str = "chat"


class CoachExecIn(BaseModel):
    session_id: int
    command: str


class CheckpointIn(BaseModel):
    session_id: int
    checkpoint_id: str


class EngineStatusOut(BaseModel):
    mode: str
    health: dict
    resources: dict
    node: dict | None = None
