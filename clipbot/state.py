"""Historique SQLite des clips traités (évite les doublons, alimente l'interface de revue)."""

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
    status      TEXT NOT NULL,      -- rendered | published | rejected | failed
    output_path TEXT,
    caption     TEXT,
    publish_id  TEXT,
    error       TEXT,
    updated_at  INTEGER NOT NULL
);
"""

DONE_STATUSES = ("rendered", "published", "rejected")


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # l'interface de revue sert les requêtes depuis plusieurs threads
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(clips)")}
        if "caption" not in cols:  # base créée par la v0.1
            self.conn.execute("ALTER TABLE clips ADD COLUMN caption TEXT")

    def get(self, clip_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM clips WHERE clip_id = ?", (clip_id,)).fetchone()
        return dict(row) if row else None

    def is_done(self, clip_id: str) -> bool:
        row = self.get(clip_id)
        return row is not None and row["status"] in DONE_STATUSES

    def is_published(self, clip_id: str) -> bool:
        row = self.get(clip_id)
        return row is not None and row["status"] == "published"

    def list(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM clips WHERE status = ? ORDER BY updated_at DESC", (status,)
            )
        else:
            rows = self.conn.execute("SELECT * FROM clips ORDER BY updated_at DESC")
        return [dict(r) for r in rows]

    def record(self, clip_id: str, channel: str, status: str, **fields) -> None:
        cols = {"title": None, "url": None, "view_count": None, "output_path": None,
                "caption": None, "publish_id": None, "error": None, **fields}
        self.conn.execute(
            """INSERT INTO clips (clip_id, channel, title, url, view_count, status,
                                  output_path, caption, publish_id, error, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(clip_id) DO UPDATE SET
                 status=excluded.status,
                 output_path=COALESCE(excluded.output_path, clips.output_path),
                 caption=COALESCE(excluded.caption, clips.caption),
                 publish_id=COALESCE(excluded.publish_id, clips.publish_id),
                 error=excluded.error,
                 updated_at=excluded.updated_at""",
            (clip_id, channel, cols["title"], cols["url"], cols["view_count"], status,
             cols["output_path"], cols["caption"], cols["publish_id"], cols["error"],
             int(time.time())),
        )
        self.conn.commit()
