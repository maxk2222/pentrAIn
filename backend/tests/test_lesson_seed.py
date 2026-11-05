"""Repo seed → coach_lessons (boot path, idempotent)."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.models.domain import CoachLesson
from app.services import coach_bridge


async def test_seed_lessons_creates_and_dedupes(db, tmp_path):
    seed = tmp_path / "lessons.json"
    seed.write_text(json.dumps([
        {"text": "Use jq for JSON parsing instead of grep/cut chains.",
         "tags": ["jq", "json"], "applies": "global", "confidence": 0.9},
        {"text": "Use jq for JSON parsing instead of grep chains.",
         "tags": ["jq"]},
        {"not_a_lesson": True},
    ]))
    n = await coach_bridge.seed_lessons(db, seed)
    rows = list((await db.execute(select(CoachLesson))).scalars().all())
    assert n >= 1 and len(rows) == 1          # jaccard merge + malformed skip
    assert rows[0].source == "seed" and rows[0].session_id is None

    await coach_bridge.seed_lessons(db, seed)  # restart rerun — no dupes
    assert len(list((await db.execute(
        select(CoachLesson))).scalars().all())) == 1


async def test_seed_lessons_tolerates_missing_file(db, tmp_path):
    assert await coach_bridge.seed_lessons(db, tmp_path / "none.json") == 0
