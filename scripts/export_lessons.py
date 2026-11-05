#!/usr/bin/env python3
"""Export active coach_lessons from a live pentrain.db as the repo seed.

Usage: python scripts/export_lessons.py /path/to/pentrain.db > content/knowledge/lessons.json

Keep this curated: review rows first (admin lessons queue), disable noise,
then export. Rows are text/tags/applies/confidence only — session ids,
hits and evidence stay local.
"""
from __future__ import annotations

import json
import sqlite3
import sys


def main(db_path: str) -> int:
    db = sqlite3.connect(db_path)
    rows = db.execute(
        "SELECT text, tags, applies, confidence FROM coach_lessons "
        "WHERE status='active' ORDER BY id").all()
    out = [{"text": t, "tags": json.loads(tags or "[]"),
            "applies": applies or "global",
            "confidence": conf if conf is not None else 0.5}
           for t, tags, applies, conf in rows]
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
