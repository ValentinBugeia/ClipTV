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
    old = time.time() - 8 * 86400  # au-delà de 7 jours : oublié
    st.save_settings({"discovered": {"vieux": {"id": "1", "seen": old},
                                      "hier": {"id": "2", "seen": time.time() - 86400}}})
    tw = FakeTwitch([{"user_login": "Kamet0", "user_id": "3"}], {})
    chans = candidate_channels(tw, st, language="fr", streamers=30, favorites=["perso"])
    assert chans == {"hier": "2", "kamet0": "3", "perso": "id-perso"}
    assert tw.calls[0][1] == {"first": 100, "type": "live", "language": "fr"}
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


class FakeTwitchCategories(FakeTwitch):
    """Lives + clips les plus vus par catégorie (chaînes hors ligne comprises)."""

    def __init__(self, streams, clips, game_clips, logins):
        super().__init__(streams, clips)
        self.game_clips, self._logins = game_clips, logins

    def get_game_clips(self, game_id, *, since_hours, limit):
        return self.game_clips.get(game_id, [])

    def logins(self, ids):
        return {i: self._logins[i] for i in ids if i in self._logins}


def test_discover_adds_viral_category_clips(tmp_path):
    streams = [{"user_login": "petit", "user_id": "id-petit", "game_id": "jc",
                "viewer_count": 900}]
    small = [clip(f"p{i}", "petit", 40 + i) for i in range(3)]  # 40 vues : pas un moment fort
    viral = [clip(f"v{i}", f"star{i}", 8000 - i * 500) for i in range(12)]
    for i, c in enumerate(viral):
        c.broadcaster_id = f"id-star{i}"
    viral.append(clip("en", "anglais", 99999, lang="en"))
    twitch = FakeTwitchCategories(streams, {"id-petit": small}, {"jc": viral},
                                  {f"id-star{i}": f"star{i}" for i in range(12)})
    found = discover(twitch, state(tmp_path), language="fr", streamers=5, top=3, min_views=0)
    assert [login for _, login in found] == ["star0", "star1", "star2"]  # hors ligne compris
    assert all(c.language == "fr" for c, _ in found)


def test_standout_ignores_tiny_numbers():
    from clipbot.discover import standout_score

    clips = [clip("a", "petit", 10), clip("b", "petit", 12), clip("c", "petit", 11),
             clip("d", "petit", 49)]
    standout_score(clips)
    assert clips[-1].standout < 2  # 49 vues contre ~11 : pas « hors norme »


def test_morning_search_uses_last_night_categories(tmp_path):
    """Relevé de la veille au soir (app ouverte) : à 8 h, plus aucun live dans la catégorie,
    mais ses meilleurs clips des dernières 24 h sont quand même cherchés."""
    from clipbot.discover import remember_streams

    st = state(tmp_path)
    remember_streams(st, [{"user_login": "soiree", "user_id": "id-soiree", "game_id": "gta",
                           "viewer_count": 20000}])
    viral = [clip(f"g{i}", f"rp{i}", 9000 - i * 300) for i in range(10)]
    for i, c in enumerate(viral):
        c.broadcaster_id = f"id-rp{i}"
    morning = [{"user_login": "matin", "user_id": "id-matin", "viewer_count": 50}]  # pas de GTA
    twitch = FakeTwitchCategories(morning, {}, {"gta": viral},
                                  {f"id-rp{i}": f"rp{i}" for i in range(10)})
    found = discover(twitch, st, language="fr", streamers=5, top=2, min_views=0)
    assert [login for _, login in found] == ["rp0", "rp1"]


def test_last_night_hit_beats_small_fresh_clip():
    from clipbot.discover import standout_score

    fresh = clip("fresh", "a", 400, hours_ago=1)
    hit = clip("hit", "b", 5000, hours_ago=20)  # moment fort de la veille au soir
    score = standout_score([fresh, hit])
    assert fresh.virality() > hit.virality()       # l'ancien classement se trompait
    assert score(hit) > score(fresh)


def test_audience_share_levels_big_and_small_streamers():
    from clipbot.discover import standout_score

    big = clip("big", "gros", 2000, hours_ago=3)     # 30 000 spectateurs : 7 %, banal
    small = clip("small", "petit", 500, hours_ago=3)  # 800 spectateurs : 62 %, énorme
    viewers = {"gros": 30000, "petit": 800}
    score = standout_score([big, small], lambda c: viewers[c.broadcaster_name])
    assert small.audience_share > 0.6 and score(small) > score(big)
