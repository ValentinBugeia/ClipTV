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
        """``streams`` = chaînes qui ont diffusé sur la période (renvoyées comme rediffusions)."""
        self.calls.append((path, params))
        if path == "/games/top":
            return {"data": [{"id": "jc", "name": "Just Chatting"}]}
        if path == "/videos":
            return {"data": [{"user_login": s["user_login"], "user_id": s["user_id"],
                              "view_count": s.get("viewer_count", 100)} for s in self.streams]}
        return {"data": []}

    def get_broadcaster_id(self, login):
        return f"id-{login}"

    def get_clips(self, broadcaster_id, *, since_hours, limit):
        return self.clips.get(broadcaster_id, [])


def state(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    return State(cfg.db_path)


def test_pick_clips_most_viewed_in_language():
    clips = [clip("a1", "Kamet0", 5000), clip("a2", "Kamet0", 4000),
             clip("b1", "Zerator", 3000), clip("en", "xqc", 9000, lang="en"),
             clip("c1", "Gotaga", 20), clip("long", "Gotaga", 8000, duration=90)]
    picked = pick_clips(clips, {}, top=3, language="fr", is_done=lambda cid: cid == "b1")
    assert [(c.id, login) for c, login in picked] == [("a1", "kamet0"), ("a2", "kamet0"),
                                                      ("c1", "gotaga")]


def test_pick_clips_one_clip_per_moment():
    a, b, c = clip("a", "k", 900), clip("b", "k", 800), clip("c", "k", 700)
    for x, off in ((a, 100.0), (b, 110.0), (c, 400.0)):
        x.video_id, x.vod_offset = "v1", off  # a et b : même moment de la rediffusion
    picked = pick_clips([a, b, c], {}, top=2)
    assert [x.id for x, _ in picked] == ["a", "c"] and a.clippers == 2


def test_candidates_are_the_most_viewed_streamers(tmp_path):
    """Streamers les plus vus de la période (vues des rediffusions), plus les plus
    regardés en live ces 7 derniers jours (même sans rediffusion), plus les favoris ;
    aucun appel aux lives en cours."""
    st = state(tmp_path)
    st.save_settings({"discovered": {"sansvod": {"id": "2", "seen": time.time() - 3600,
                                                 "viewers": 40000}}})
    tw = FakeTwitch([{"user_login": "Kamet0", "user_id": "3"}], {})
    chans = candidate_channels(tw, st, language="fr", favorites=["perso"])
    assert chans == {"kamet0": "3", "sansvod": "2", "perso": "id-perso"}
    assert not any(path == "/streams" for path, _ in tw.calls)
    videos = [params for path, params in tw.calls if path == "/videos"]
    assert videos and videos[0]["language"] == "fr" and videos[0]["period"] == "day"


def test_only_the_most_viewed_streamers_are_scanned(tmp_path, monkeypatch):
    from clipbot import discover as d

    monkeypatch.setattr(d, "TOP_STREAMERS", 2)
    tw = FakeTwitch([{"user_login": f"s{i}", "user_id": f"id{i}", "viewer_count": 1000 - i}
                     for i in range(5)], {})
    assert list(candidate_channels(tw, state(tmp_path), language="fr")) == ["s0", "s1"]


def test_discover_takes_the_most_viewed(tmp_path):
    st = state(tmp_path)
    tw = FakeTwitch(
        [{"user_login": "kamet0", "user_id": "k"}, {"user_login": "zerator", "user_id": "z"}],
        {"k": [clip("k1", "kamet0", 3000, hours_ago=20)],  # la veille au soir : le plus vu
         "z": [clip("z1", "zerator", 400, hours_ago=1),
               clip("z2", "zerator", 350, hours_ago=1)]})
    result = discover(tw, st, language="fr", top=2)
    assert [(c.id, login) for c, login in result] == [("k1", "kamet0"), ("z1", "zerator")]


class FakeTwitchCategories(FakeTwitch):
    """Lives + clips les plus vus par catégorie (chaînes hors ligne comprises)."""

    def __init__(self, streams, clips, game_clips, logins):
        super().__init__(streams, clips)
        self.game_clips, self._logins = game_clips, logins

    def get_game_clips(self, game_id, *, since_hours, limit):
        return self.game_clips.get(game_id, [])

    def logins(self, ids):
        return {i: self._logins[i] for i in ids if i in self._logins}


class FakeTwitchSearch(FakeTwitchCategories):
    def _get(self, path, params):
        if path == "/search/categories":
            names = {"valorant": [{"id": "val", "name": "VALORANT"}],
                     "just": [{"id": "jc", "name": "Just Chatting"}]}
            return {"data": names.get(params["query"].lower().split()[0], [])}
        return super()._get(path, params)

    def get_broadcaster_id(self, login):
        if login.lower() != "gotaga":
            raise ValueError("introuvable")
        return "id-gotaga"


def test_free_text_search_resolves_channel_game_and_keyword(tmp_path):
    from clipbot.discover import resolve_query

    tw = FakeTwitchSearch([], {}, {}, {})
    q = resolve_query(tw, ["Valorant", "gotaga", "fou rire", "just chat"])
    assert q["games"] == {"val": "VALORANT", "jc": "Just Chatting"}
    assert q["channels"] == {"gotaga": "id-gotaga"} and q["keywords"] == ["fou rire"]


def test_channel_search_returns_several_clips_of_that_channel(tmp_path):
    clips = [clip(f"g{i}", "Gotaga", 300 - i * 10, lang="en") for i in range(5)]
    tw = FakeTwitchSearch([], {"id-gotaga": clips}, {}, {})
    found = discover(tw, state(tmp_path), language="fr", top=3, query=["gotaga"])
    assert [c.id for c, _ in found] == ["g0", "g1", "g2"]  # même chaîne, toute langue


class FakeTwitchVods(FakeTwitch):
    """Aucun live le matin, mémoire vide (app fermée la veille), mais Twitch liste les
    rediffusions FR d'hier soir."""

    def _get(self, path, params):
        self.calls.append((path, params))
        if path == "/streams":
            return {"data": []}
        if path == "/games/top":
            return {"data": [{"id": "jc", "name": "Just Chatting"}]}
        if path == "/videos":
            assert params["language"] == "fr" and params["period"] == "day"
            return {"data": [{"user_login": "Gotaga", "user_id": "id-gotaga", "view_count": 90000},
                             {"user_login": "petit", "user_id": "id-petit", "view_count": 300}]}
        return {"data": []}


def test_morning_search_finds_last_night_streams_with_app_closed(tmp_path):
    clips = {"id-gotaga": [clip("hier", "Gotaga", 6000, hours_ago=10)],
             "id-petit": [clip("p", "petit", 150, hours_ago=11)]}
    tw = FakeTwitchVods([], clips)
    found = discover(tw, state(tmp_path), language="fr", hours=24, top=1)
    assert [(c.id, login) for c, login in found] == [("hier", "gotaga")]
