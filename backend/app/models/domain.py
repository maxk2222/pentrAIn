"""Domain models (SQLAlchemy 2, declarative)."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionState(str, enum.Enum):
    QUEUED = "queued"
    DEPLOYING = "deploying"
    READY = "ready"
    ACTIVE = "active"
    SOLVED = "solved"
    ABORTED = "aborted"
    FAILED = "failed"
    RESETTING = "resetting"
    ABORTING = "aborting"


class FlagKind(str, enum.Enum):
    FILE = "file"        # secret injected into a file on the target
    COMMAND = "command"  # state flag verified by a command on the target (v2)


class AutonomyLevel(int, enum.Enum):
    SPECTATE = 1
    ADVISOR = 2
    COPILOT = 3
    TAKEOVER = 4


class Track(Base):
    __tablename__ = "tracks"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(64), default="target")
    order: Mapped[int] = mapped_column(Integer, default=0)
    cheatsheet_md: Mapped[str] = mapped_column(Text, default="")  # track-level reference card

    quests: Mapped[list[Quest]] = relationship(back_populates="track", order_by="Quest.tier")


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. web-sqli-01
    track_slug: Mapped[str] = mapped_column(ForeignKey("tracks.slug"), index=True)
    tier: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    pack_path: Mapped[str] = mapped_column(String(500))   # abs path to quest dir
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    exam: Mapped[bool] = mapped_column(Boolean, default=False)  # capstone — unlocks only when all same-tier quests are solved

    requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    topology: Mapped[dict] = mapped_column(JSON, default=dict)
    scoring_cfg: Mapped[dict] = mapped_column(JSON, default=dict)
    hints_cfg: Mapped[list] = mapped_column(JSON, default=list)
    coach_cfg: Mapped[dict] = mapped_column(JSON, default=dict)

    briefing_md: Mapped[str] = mapped_column(Text, default="")
    defense_md: Mapped[str] = mapped_column(Text, default="")
    cheatsheet_md: Mapped[str] = mapped_column(Text, default="")    # optional quest reference card
    coach_context_md: Mapped[str] = mapped_column(Text, default="")  # hidden from UI

    track: Mapped[Track] = relationship(back_populates="quests")
    flags: Mapped[list[Flag]] = relationship(back_populates="quest", cascade="all, delete-orphan")


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quest_id: Mapped[str] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))          # e.g. flag1
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default=FlagKind.FILE.value)
    points: Mapped[int] = mapped_column(Integer, default=100)
    # kind=command: verification spec, e.g. {"vm":"web01","cmd":"id -u backdoor","expect":"0"}
    command_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    quest: Mapped[Quest] = relationship(back_populates="flags")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quest_id: Mapped[str] = mapped_column(ForeignKey("quests.id"), index=True)
    state: Mapped[str] = mapped_column(String(16), default=SessionState.QUEUED.value, index=True)
    range_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kali_vmid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_vmids: Mapped[dict] = mapped_column(JSON, default=dict)  # name -> vmid
    flag_seed: Mapped[str] = mapped_column(String(64), default="")
    telemetry_token: Mapped[str] = mapped_column(String(64), default="")
    autonomy_level: Mapped[int] = mapped_column(Integer, default=AutonomyLevel.ADVISOR.value)
    deploy_log: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    coach_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    kali_internet: Mapped[bool] = mapped_column(Boolean, default=False)  # net1→wan bridge attached
    kali_wan_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)  # LAN lease on net1 — scope auto-detect
    kali_tools: Mapped[str] = mapped_column(Text, default="")  # live `command -v` probe results
    # L4 parallel worker agents (spawn_agent → tmux windows w1..w3)
    subagents_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # engagement ROE snapshot — normalized whitelist the coach enforces as
    # a HARD boundary (see services/scope.py); NULL = unlocked LAN/range mode
    scope_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    quest: Mapped[Quest] = relationship()


class ExpectedFlag(Base):
    """Per-session flag secret (dynamic flags are unique per attempt)."""
    __tablename__ = "expected_flags"
    __table_args__ = (UniqueConstraint("session_id", "flag_key", name="uq_expected_flag"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    flag_key: Mapped[str] = mapped_column(String(64))
    secret: Mapped[str] = mapped_column(String(128))


class FlagSubmission(Base):
    __tablename__ = "flag_submissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    flag_key: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(256))
    correct: Mapped[bool] = mapped_column(Boolean)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("session_id", name="uq_attempt_session"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quest_id: Mapped[str] = mapped_column(ForeignKey("quests.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    flags_found: Mapped[int] = mapped_column(Integer, default=0)
    flags_total: Mapped[int] = mapped_column(Integer, default=0)
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    coach_interventions: Mapped[int] = mapped_column(Integer, default=0)
    # which aids were used: {hints, coach_msgs, coach_nudges, takeovers, sheet, chat}
    assistance: Mapped[dict] = mapped_column(JSON, default=dict)
    # score decomposition: {flags, time_bonus, hint_cost, takeover_penalty, par_s}
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    # a session can be soft-reset and re-solved — row tracks the LATEST run
    runs: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AssistUse(Base):
    """UI-side aid the trainee opted into (lazy-modal confirms sheet/chat opens)."""
    __tablename__ = "assist_uses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # sheet|chat
    used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    kind: Mapped[str] = mapped_column(String(32))  # command|output|net|ui|flag|deploy
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # no FK — usage rows survive session deletion
    session_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    model: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(24), default="chat")  # chat|reflect|vision
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


class CoachMessage(Base):
    __tablename__ = "coach_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # coach|user|system
    kind: Mapped[str] = mapped_column(String(24), default="chat")  # chat|hint|nudge|suggestion|action_report
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CoachAction(Base):
    __tablename__ = "coach_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|denied|error|confirmed|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CoachLesson(Base):
    """Observer-authored field note — reusable tips distilled from real
    coach sessions (stuck→recovery analysis, postmortems). Distinct from
    curated knowledge modules: written by the observer service, labeled
    'unverified' when shown to the coach, scoped global/track/quest."""
    __tablename__ = "coach_lessons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        Integer, index=True, nullable=True)  # origin session (no FK — survives deletion)
    text: Mapped[str] = mapped_column(String(240))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    applies: Mapped[str] = mapped_column(String(80), default="global")  # global|track:X|quest:Y
    status: Mapped[str] = mapped_column(String(16), default="active")   # active|disabled
    confidence: Mapped[float] = mapped_column(default=0.5)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)          # {session_id, summary, window}
    hits: Mapped[int] = mapped_column(Integer, default=0)
    misses: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(24), default="observer")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HintUse(Base):
    __tablename__ = "hint_uses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    hint_id: Mapped[str] = mapped_column(String(64))
    cost: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QuestCheckpoint(Base):
    __tablename__ = "quest_checkpoints"
    __table_args__ = (UniqueConstraint("session_id", "checkpoint_id", name="uq_checkpoint"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    checkpoint_id: Mapped[str] = mapped_column(String(64))
    hit_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(primary_key=True)  # always 1 in v1
    xp_total: Mapped[int] = mapped_column(Integer, default=0)
    track_levels: Mapped[dict] = mapped_column(JSON, default=dict)   # {"web-appsec": 2, ...}
    prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)        # rolling stats for coach


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CoachSessionState(Base):
    """Persisted coach working memory per session (survives restarts)."""
    __tablename__ = "coach_session_state"

    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
