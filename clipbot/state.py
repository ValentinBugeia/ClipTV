"""Historique SQLite des clips traités (évite les doublons)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    clip_id     TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,
    title       TEXT,
    url         TEXT,
    view_count  INTEGER,
    status      TEXT NOT NULL,      -- rendered | published | failed
    output_path TEXT,
    publish_id  TEXT,
    error       TEXT,
    updated_at  INTEGER NOT NULL
);
"""


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(SCHEMA)

    def is_done(self, clip_id: str) -> bool:
        row = self.conn.execute(
            "SELECT status FROM clips WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        return row is not None and row[0] in ("rendered", "published")

    def is_published(self, clip_id: str) -> bool:
        row = self.conn.execute(
            "SELECT status FROM clips WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        return row is not None and row[0] == "published"

    def record(self, clip_id: str, channel: str, status: str, **fields) -> None:
        cols = {"title": None, "url": None, "view_count": None, "output_path": None,
                "publish_id": None, "error": None, **fields}
        self.conn.execute(
            """INSERT INTO clips (clip_id, channel, title, url, view_count, status,
                                  output_path, publish_id, error, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(clip_id) DO UPDATE SET
                 status=excluded.status,
                 output_path=COALESCE(excluded.output_path, clips.output_path),
                 publish_id=COALESCE(excluded.publish_id, clips.publish_id),
                 error=excluded.error,
                 updated_at=excluded.updated_at""",
            (clip_id, channel, cols["title"], cols["url"], cols["view_count"], status,
             cols["output_path"], cols["publish_id"], cols["error"], int(time.time())),
        )
        self.conn.commit()
