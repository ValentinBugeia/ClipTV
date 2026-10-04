import time

from clipbot import stats
from clipbot.config import Config
from clipbot.state import State
from clipbot.stats_page import compact, render
from clipbot.tiktok import authorize_url


def make(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    cfg.tiktok_client_key = cfg.tiktok_client_secret = "x"
    st = State(cfg.db_path)
    st.record("c1", "kamet0", "published", caption="Il rage sur le boss final 😂 #fyp",
              category="Elden Ring")
    st.record("c2", "zerator", "published", caption="Clutch de l'année en 1v4 #valorant",
              category="VALORANT")
    st.record_post("c1", "tiktok", "ok", post_id="pub-1")
    return cfg, st


class FakeClient:
    def account_stats(self):
        return {"follower_count": 1234, "likes_count": 98765}

    def list_videos(self):
        now = int(time.time())
        return [
            {"id": 111, "video_description": "Il rage sur le boss final 😂 #fyp", "create_time": now - 3600,
             "view_count": 5000, "like_count": 400, "comment_count": 30, "share_count": 20},
            {"id": 222, "video_description": "Clutch de l'année en 1v4 #valorant", "create_time": now - 7200,
             "view_count": 20000, "like_count": 2500, "comment_count": 100, "share_count": 400},
            {"id": 333, "video_description": "Vidéo postée à la main", "create_time": now - 900,
             "view_count": 50, "like_count": 1, "comment_count": 0, "share_count": 0},
        ]

    def status(self, publish_id):
        return {"publicaly_available_post_id": [111]} if publish_id == "pub-1" else {}


def test_refresh_links_and_summarizes(tmp_path, monkeypatch):
    cfg, st = make(tmp_path)
    monkeypatch.setattr(stats, "_client", lambda cfg: FakeClient())
    assert stats.refresh(cfg, st) == "3 vidéo(s) TikTok mises à jour"
    by_id = {v["video_id"]: v for v in st.videos()}
    assert by_id["111"]["clip_id"] == "c1"       # via le suivi de publication
    assert by_id["222"]["clip_id"] == "c2"       # via la légende
    assert by_id["333"]["clip_id"] is None

    s = stats.summary(st, since=0, tz="Europe/Paris")
    assert s["totals"]["views"] == 25050 and s["account"]["follower_count"] == 1234
    assert s["by_channel"][0][0] == "zerator" and s["by_category"][0][0] == "VALORANT"
    html = render(s, days=30, sort="views", tz="Europe/Paris")
    assert "Vues moyennes par streamer" in html and "zerator" in html and "1 234" in html


def test_refresh_error_is_reported(tmp_path, monkeypatch):
    cfg, st = make(tmp_path)

    class Refuse(FakeClient):
        def list_videos(self):
            raise RuntimeError("scope_not_authorized video.list")

    monkeypatch.setattr(stats, "_client", lambda cfg: Refuse())
    msg = stats.refresh(cfg, st)
    assert "Display API" in msg and "Reconnecter TikTok" in msg
    assert st.get_settings()["stats_error"] == msg


def test_stats_scopes_only_when_enabled():
    assert "video.list" not in authorize_url("k", "https://ex.com/cb")
    assert "user.info.stats" in authorize_url("k", "https://ex.com/cb", stats=True)


def test_compact():
    assert compact(950) == "950" and compact(12900) == "12,9 k" and compact(4_200_000) == "4,2 M"
