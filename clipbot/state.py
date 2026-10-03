"""Historique SQLite des clips traités (évite les doublons, alimente l'interface de revue).

Cycle de vie d'un clip :
    rendered ──► scheduled ──► publishing ──► published
        │            │                   └──► failed (réessayable depuis la revue)
        └──► rejected └──► rendered (programmation annulée)

La table ``posts`` garde le résultat par plateforme : en cas d'échec partiel, une
nouvelle tentative ne republie pas sur les plateformes déjà réussies.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    clip_id      TEXT PRIMARY KEY,
    channel      TEXT NOT NULL,
    title        TEXT,
    url          TEXT,
    view_count   INTEGER,
    status       TEXT NOT NULL,     -- rendered | scheduled | publishing | published | rejected | failed
    output_path  TEXT,
    caption      TEXT,
    publish_id   TEXT,
    error        TEXT,
    scheduled_at INTEGER,
    updated_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    clip_id    TEXT NOT NULL,
    platform   TEXT NOT NULL,       -- tiktok | youtube | instagram
    status     TEXT NOT NULL,       -- ok | failed
    post_id    TEXT,
    error      TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (clip_id, platform)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL             -- JSON
);
"""

DONE_STATUSES = ("rendered", "scheduled", "publishing", "published", "rejected")
# statuts depuis lesquels une publication peut être lancée
PUBLISHABLE = ("rendered", "scheduled", "failed")


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # partagé entre les threads de la revue et le planificateur ; d'autres process
        # (run, watch) écrivent dans la même base, d'où le timeout
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.executescript(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(clips)")}
        for col, typ in (("caption", "TEXT"), ("scheduled_at", "INTEGER")):  # bases v0.1/v0.2
            if col not in cols:
                self.conn.execute(f"ALTER TABLE clips ADD COLUMN {col} {typ}")
        self.conn.commit()

    def _write(self, sql: str, params: tuple = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.rowcount

    def get(self, clip_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM clips WHERE clip_id = ?",
                                    (clip_id,)).fetchone()
        return dict(row) if row else None

    def is_done(self, clip_id: str) -> bool:
        row = self.get(clip_id)
        return row is not None and row["status"] in DONE_STATUSES

    def is_published(self, clip_id: str) -> bool:
        row = self.get(clip_id)
        return row is not None and row["status"] == "published"

    def list(self, status: str | None = None) -> list[dict]:
        order = "scheduled_at ASC" if status == "scheduled" else "updated_at DESC"
        with self.lock:
            if status:
                rows = self.conn.execute(
                    f"SELECT * FROM clips WHERE status = ? ORDER BY {order}", (status,))
            else:
                rows = self.conn.execute(f"SELECT * FROM clips ORDER BY {order}")
            return [dict(r) for r in rows]

    def count(self, status: str) -> int:
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM clips WHERE status = ?",
                                     (status,)).fetchone()[0]

    def record(self, clip_id: str, channel: str, status: str, **fields) -> None:
        cols = {"title": None, "url": None, "view_count": None, "output_path": None,
                "caption": None, "publish_id": None, "error": None, "scheduled_at": None,
                **fields}
        self._write(
            """INSERT INTO clips (clip_id, channel, title, url, view_count, status,
                                  output_path, caption, publish_id, error, scheduled_at,
                                  updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(clip_id) DO UPDATE SET
                 status=excluded.status,
                 output_path=COALESCE(excluded.output_path, clips.output_path),
                 caption=COALESCE(excluded.caption, clips.caption),
                 publish_id=COALESCE(excluded.publish_id, clips.publish_id),
                 error=excluded.error,
                 scheduled_at=excluded.scheduled_at,
                 updated_at=excluded.updated_at""",
            (clip_id, channel, cols["title"], cols["url"], cols["view_count"], status,
             cols["output_path"], cols["caption"], cols["publish_id"], cols["error"],
             cols["scheduled_at"], int(time.time())),
        )

    # ---------- programmation ----------
    def schedule(self, clip_id: str, when: int, caption: str | None = None) -> bool:
        return self._write(
            """UPDATE clips SET status='scheduled', scheduled_at=?, error=NULL,
                      caption=COALESCE(?, caption), updated_at=?
               WHERE clip_id=? AND status IN ('rendered', 'failed', 'scheduled')""",
            (int(when), caption, int(time.time()), clip_id)) == 1

    def unschedule(self, clip_id: str) -> bool:
        return self._write(
            """UPDATE clips SET status='rendered', scheduled_at=NULL, updated_at=?
               WHERE clip_id=? AND status='scheduled'""",
            (int(time.time()), clip_id)) == 1

    def scheduled_times(self) -> list[int]:
        with self.lock:
            return [r[0] for r in self.conn.execute(
                "SELECT scheduled_at FROM clips WHERE status='scheduled' "
                "AND scheduled_at IS NOT NULL")]

    def due(self, now: float) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM clips WHERE status='scheduled' AND scheduled_at <= ? "
                "ORDER BY scheduled_at", (int(now),))
            return [dict(r) for r in rows]

    def claim(self, clip_id: str, caption: str | None = None) -> bool:
        """Passe le clip en ``publishing`` de façon atomique (un seul publieur gagne)."""
        return self._write(
            f"""UPDATE clips SET status='publishing', caption=COALESCE(?, caption), updated_at=?
                WHERE clip_id=? AND status IN ({",".join("?" * len(PUBLISHABLE))})""",
            (caption, int(time.time()), clip_id, *PUBLISHABLE)) == 1

    def recover_stuck(self, older_than: float = 3600) -> int:
        """Remet en échec les publications interrompues (crash pendant ``publishing``)."""
        return self._write(
            """UPDATE clips SET status='failed', error='publication interrompue', updated_at=?
               WHERE status='publishing' AND updated_at < ?""",
            (int(time.time()), int(time.time() - older_than)))

    # ---------- résultats par plateforme ----------
    def record_post(self, clip_id: str, platform: str, status: str, post_id: str | None = None,
                    error: str | None = None) -> None:
        self._write(
            """INSERT INTO posts (clip_id, platform, status, post_id, error, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(clip_id, platform) DO UPDATE SET status=excluded.status,
                 post_id=excluded.post_id, error=excluded.error, updated_at=excluded.updated_at""",
            (clip_id, platform, status, post_id, error, int(time.time())))

    def posts(self, clip_id: str) -> dict[str, dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM posts WHERE clip_id = ?", (clip_id,))
            return {r["platform"]: dict(r) for r in rows}

    # ---------- réglages modifiables depuis l'interface ----------
    def get_settings(self) -> dict:
        with self.lock:
            return {r["key"]: json.loads(r["value"])
                    for r in self.conn.execute("SELECT key, value FROM settings")}

    def save_settings(self, values: dict) -> None:
        with self.lock:
            self.conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(k, json.dumps(v, ensure_ascii=False)) for k, v in values.items()])
            self.conn.commit()

    def count_since(self, status: str, since: float) -> int:
        with self.lock:
            return self.conn.execute(
                "SELECT COUNT(*) FROM clips WHERE status = ? AND updated_at >= ?",
                (status, int(since))).fetchone()[0]
