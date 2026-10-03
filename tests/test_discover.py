import time
from datetime import datetime, timedelta, timezone

from clipbot.config import Config
from clipbot.discover import candidate_channels, discover, pick_clips
from clipbot.state import State
from clipbot.twitch import Clip

NOW = datetime.now(timezone.utc)


def clip(cid, chan, views, hours_ago=1, lang="fr", duration=30):
    return Clip(cid, f"https://clips.twitch.tv/{cid}", cid, chan, "x", views,
                NOW - timedelta(hours=hours_ago), duration, language=lang)


class FakeTwitch:
    def __init__(self, streams, clips):
        self.streams, self.clips, self.calls = streams, clips, []

    def _get(self, path, params):
        self.calls.append((path, params))
        assert path == "/streams"
        return {"data": self.streams}

    def get_broadcaster_id(self, login):
        return f"id-{login}"

    def get_clips(self, broadcaster_id, *, since_hours, limit):
        return self.clips.get(broadcaster_id, [])


def state(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    return State(cfg.db_path)


def test_pick_clips_one_per_streamer_and_language():
    clips = [clip("a1", "Kamet0", 5000), clip("a2", "Kamet0", 4000),
             clip("b1", "Zerator", 3000), clip("en", "xqc", 9000, lang="en"),
             clip("c1", "Gotaga", 20, hours_ago=1)]
    picked = pick_clips(clips, top=5, min_views=50, language="fr",
                        is_done=lambda cid: cid == "b1")
    assert [c.id for c in picked] == ["a1"]
    picked = pick_clips(clips, top=5, per_channel=2, language="fr")
    assert [c.id for c in picked] == ["a1", "a2", "b1", "c1"]


def test_candidates_remember_recent_streamers(tmp_path):
    st = state(tmp_path)
    old = time.time() - 4 * 86400
    st.save_settings({"discovered": {"vieux": {"id": "1", "seen": old},
                                      "hier": {"id": "2", "seen": time.time() - 86400}}})
    tw = FakeTwitch([{"user_login": "Kamet0", "user_id": "3"}], {})
    chans = candidate_channels(tw, st, language="fr", streamers=30, favorites=["perso"])
    assert chans == {"hier": "2", "kamet0": "3", "perso": "id-perso"}
    assert tw.calls[0][1] == {"first": 30, "type": "live", "language": "fr"}
    assert set(st.get_settings()["discovered"]) == {"hier", "kamet0"}


def test_discover_ranks_across_streamers(tmp_path):
    st = state(tmp_path)
    tw = FakeTwitch(
        [{"user_login": "kamet0", "user_id": "k"}, {"user_login": "zerator", "user_id": "z"}],
        {"k": [clip("k1", "kamet0", 300, hours_ago=3)],             # 100 vues/h
         "z": [clip("z1", "zerator", 400, hours_ago=1),             # 400 vues/h
               clip("z2", "zerator", 350, hours_ago=1)]})
    result = discover(tw, st, language="fr", top=2, min_views=50)
    assert [(c.id, login) for c, login in result] == [("z1", "zerator"), ("k1", "kamet0")]
