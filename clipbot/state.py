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
    category     TEXT,
    signals      TEXT,              -- JSON : indices de potentiel (vues Twitch, durée…)
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
CREATE TABLE IF NOT EXISTS tiktok_videos (
    video_id    TEXT PRIMARY KEY,
    title       TEXT,
    description TEXT,
    create_time INTEGER,
    cover       TEXT,
    share_url   TEXT,
    views       INTEGER,
    likes       INTEGER,
    comments    INTEGER,
    shares      INTEGER,
    duration    INTEGER,
    clip_id     TEXT,               -- clip cliptv d'origine, si reconnu
    updated_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_activity (
    channel TEXT NOT NULL,
    bucket  INTEGER NOT NULL,       -- début de la tranche de 10 s (timestamp)
    weight  REAL NOT NULL,          -- activité pondérée du chat (réactions fortes x2)
    PRIMARY KEY (channel, bucket)
);
CREATE TABLE IF NOT EXISTS claude_usage (
    at         INTEGER NOT NULL,    -- timestamp
    purpose    TEXT NOT NULL,       -- juré, légende…
    tokens_in  INTEGER NOT NULL,    -- lus (dont cache)
    tokens_out INTEGER NOT NULL,    -- écrits
    cost       REAL NOT NULL,       -- équivalent API en $ (non facturé avec l'abonnement)
    ms         INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL             -- JSON
);
"""

# « purged » : rejeté puis supprimé (fichiers effacés) ; gardé pour ne pas le reproposer
DONE_STATUSES = ("rendered", "scheduled", "publishing", "published", "rejected", "purged")
# clip non choisi, écarté automatiquement par une nouvelle recherche (pas un refus de ta part)
AUTO_REJECT = "remplacé par une nouvelle recherche"
REJECTED_KEEP = 10
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
        for col, typ in (("caption", "TEXT"), ("scheduled_at", "INTEGER"),
                         ("category", "TEXT"), ("signals", "TEXT")):  # anciennes bases
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

    def version(self) -> str:
        """Change dès qu'un clip est ajouté ou change d'état (actualisation de la page)."""
        with self.lock:
            n, last = self.conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(updated_at), 0) FROM clips").fetchone()
        return f"{n}-{last}"

    def count(self, status: str) -> int:
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM clips WHERE status = ?",
                                     (status,)).fetchone()[0]

    def record(self, clip_id: str, channel: str, status: str, **fields) -> None:
        cols = {"title": None, "url": None, "view_count": None, "output_path": None,
                "caption": None, "publish_id": None, "error": None, "scheduled_at": None,
                "category": None, "signals": None, **fields}
        self._write(
            """INSERT INTO clips (clip_id, channel, title, url, view_count, status,
                                  output_path, caption, publish_id, error, scheduled_at,
                                  category, signals, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(clip_id) DO UPDATE SET
                 status=excluded.status,
                 output_path=COALESCE(excluded.output_path, clips.output_path),
                 caption=COALESCE(excluded.caption, clips.caption),
                 publish_id=COALESCE(excluded.publish_id, clips.publish_id),
                 error=excluded.error,
                 scheduled_at=excluded.scheduled_at,
                 category=COALESCE(excluded.category, clips.category),
                 signals=COALESCE(excluded.signals, clips.signals),
                 updated_at=excluded.updated_at""",
            (clip_id, channel, cols["title"], cols["url"], cols["view_count"], status,
             cols["output_path"], cols["caption"], cols["publish_id"], cols["error"],
             cols["scheduled_at"], cols["category"], cols["signals"], int(time.time())),
        )

    def archive_pending(self) -> int:
        """Nouvelle recherche : les clips encore « à publier » passent dans « Rejetés »,
        pour ne voir que ceux de la dernière recherche."""
        n = self._write("UPDATE clips SET status='rejected', error=?, updated_at=? "
                        "WHERE status='rendered'", (AUTO_REJECT, int(time.time())))
        return n

    def trim_rejected(self, downloads_dir: Path | None = None, keep: int = REJECTED_KEEP) -> int:
        """Garde les ``keep`` rejetés les plus récents ; les plus anciens sont supprimés
        (vidéo, sous-titres, source téléchargée). La ligne reste (statut « purged ») pour
        que le clip ne soit pas reproposé."""
        with self.lock:
            old = [dict(r) for r in self.conn.execute(
                "SELECT clip_id, output_path FROM clips WHERE status='rejected' "
                "ORDER BY updated_at DESC, rowid DESC LIMIT -1 OFFSET ?", (keep,))]
        for row in old:
            files = []
            if row["output_path"]:
                out = Path(row["output_path"])
                files += [out, out.with_suffix(".ass")]
            if downloads_dir:
                files += list(Path(downloads_dir).glob(f"{row['clip_id']}.*"))
            for f in files:
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
            self._write("UPDATE clips SET status='purged', output_path=NULL WHERE clip_id=?",
                        (row["clip_id"],))
        return len(old)

    # ---------- utilisation de Claude (tokens) ----------
    def add_claude_usage(self, purpose: str, tokens_in: int, tokens_out: int, cost: float,
                         ms: int) -> None:
        self._write("INSERT INTO claude_usage VALUES (?,?,?,?,?,?)",
                    (int(time.time()), purpose, tokens_in, tokens_out, cost, ms))

    def claude_usage(self, since: float) -> list[dict]:
        """Par usage : appels, tokens lus / écrits, équivalent API, depuis ``since``."""
        with self.lock:
            rows = self.conn.execute(
                """SELECT purpose, COUNT(*), SUM(tokens_in), SUM(tokens_out), SUM(cost)
                   FROM claude_usage WHERE at >= ? GROUP BY purpose ORDER BY 3 DESC""",
                (int(since),)).fetchall()
        return [{"purpose": p, "calls": n, "tokens_in": i or 0, "tokens_out": o or 0,
                 "cost": c or 0.0} for p, n, i, o, c in rows]

    # ---------- activité du chat (enregistreur) ----------
    def add_chat_activity(self, rows: list[tuple[str, int, float]], keep: float = 48 * 3600) -> None:
        with self.lock:
            self.conn.executemany(
                """INSERT INTO chat_activity (channel, bucket, weight) VALUES (?,?,?)
                   ON CONFLICT(channel, bucket) DO UPDATE SET weight = weight + excluded.weight""",
                rows)
            self.conn.execute("DELETE FROM chat_activity WHERE bucket < ?",
                              (int(time.time() - keep),))
            self.conn.commit()

    def chat_activity(self, channel: str, start: float, end: float) -> dict[int, float]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT bucket, weight FROM chat_activity WHERE channel=? AND bucket>=? AND bucket<?",
                (channel.lower(), int(start), int(end))).fetchall()
        return {b: w for b, w in rows}

    def set_signals(self, clip_id: str, signals: str) -> None:
        """Met à jour les indices de potentiel sans toucher au statut ni à la programmation."""
        self._write("UPDATE clips SET signals=? WHERE clip_id=?", (signals, clip_id))

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
               WHERE status='publishing' AND updated_at <= ?""",
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

    # ---------- statistiques TikTok ----------
    VIDEO_COLS = ("video_id", "title", "description", "create_time", "cover", "share_url",
                  "views", "likes", "comments", "shares", "duration", "clip_id")

    def save_videos(self, videos: list[dict]) -> None:
        now = int(time.time())
        cols = self.VIDEO_COLS
        with self.lock:
            self.conn.executemany(
                f"""INSERT INTO tiktok_videos ({",".join(cols)}, updated_at)
                    VALUES ({",".join("?" * (len(cols) + 1))})
                    ON CONFLICT(video_id) DO UPDATE SET
                    {",".join(f"{c}=excluded.{c}" for c in cols[1:] if c != "clip_id")},
                    clip_id=COALESCE(excluded.clip_id, tiktok_videos.clip_id),
                    updated_at=excluded.updated_at""",
                [tuple(v.get(c) for c in cols) + (now,) for v in videos])
            self.conn.commit()

    def prune_videos(self, keep_ids: list[str]) -> int:
        """Retire les vidéos supprimées du compte TikTok (absentes de la dernière liste)."""
        if not keep_ids:
            return 0
        marks = ",".join("?" * len(keep_ids))
        return self._write(f"DELETE FROM tiktok_videos WHERE video_id NOT IN ({marks})",
                           tuple(keep_ids))

    def recent_videos(self, limit: int = 60) -> list[dict]:
        """Tes vidéos TikTok, les plus récentes d'abord."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM tiktok_videos ORDER BY create_time DESC LIMIT ?", (limit,))
            return [dict(r) for r in rows]

    def videos(self, since: float = 0) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM tiktok_videos WHERE create_time >= ? ORDER BY views DESC",
                (int(since),))
            return [dict(r) for r in rows]
