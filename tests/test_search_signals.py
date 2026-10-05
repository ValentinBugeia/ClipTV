"""Signaux de la recherche : chat au moment du clip, tes choix, titre, horaires, paroles."""

import time
from datetime import datetime, timezone
from types import SimpleNamespace

from clipbot import selection
from clipbot.config import Config
from clipbot.live import BUCKET, ChatRecorder, chat_spike
from clipbot.state import State


def make_state(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    return State(cfg.db_path)


def test_chat_recorder_and_spike(tmp_path):
    state = make_state(tmp_path)
    rec = ChatRecorder(state)
    now = time.time()
    moment = now - 600
    for t in range(int(moment - 3600), int(moment - 60), BUCKET):  # 1 h de chat calme
        rec.add("Nico_La", t, "salut")
    for i in range(40):  # explosion juste avant le clip
        rec.add("nico_la", moment - 20 + i * 0.2, "KEKW MDRRRR")
    rec.flush()
    spike = chat_spike(state, "Nico_La", moment)
    assert spike and spike >= 10
    assert chat_spike(state, "inconnu", moment) is None  # chat pas écouté
    clip = SimpleNamespace(broadcaster_name="nico_la",
                           created_at=datetime.fromtimestamp(moment, timezone.utc))
    assert selection.chat_factor(state, clip) == 2.0 and clip.chat_spike >= 10


def test_preferences_learn_from_choices(tmp_path):
    state = make_state(tmp_path)
    for i in range(3):
        state.record(f"p{i}", "aimé", "published", category="Valorant")
        state.record(f"r{i}", "pas_aimé", "rejected", category="Just Chatting")
    prefs = selection.preferences(state)
    liked = SimpleNamespace(broadcaster_name="Aimé", category="Valorant")
    disliked = SimpleNamespace(broadcaster_name="pas_aimé", category="Just Chatting")
    assert selection.preference_factor(liked, prefs) > 1 > selection.preference_factor(disliked, prefs)


def test_title_factor():
    assert selection.title_factor("il rage complètement") > 1
    assert selection.title_factor("KEKW le fail") > 1
    assert selection.title_factor("partie classée") == 1


def test_timing_factor():
    from clipbot.autopilot import timing_factor

    def at(hour):
        return datetime(2026, 10, 5, hour, 0, tzinfo=timezone.utc).timestamp()

    assert timing_factor("UTC", at(21)) == 0.5 and timing_factor("UTC", at(1)) == 0.5
    assert timing_factor("UTC", at(7)) == 3.0 and timing_factor("UTC", at(15)) == 1.0


def test_speech_energy():
    from clipbot.enhance import speech_energy
    from clipbot.subtitles import Word

    calm = [Word("bonjour", 0, 1), Word("à", 3, 3.2), Word("tous", 6, 7)]
    hype = [Word(w, i * 0.3, i * 0.3 + 0.25) for i, w in
            enumerate("non mais attends mdr c'est pas possible wtf".split())]
    assert speech_energy(calm)["talk_rate"] < 1
    e = speech_energy(hype)
    assert e["talk_rate"] > 2.5 and e["hype_words"] >= 3
    assert speech_energy([]) == {"talk_rate": 0.0, "hype_words": 0}


def test_proven_channels(tmp_path):
    from clipbot.discover import proven_channels

    state = make_state(tmp_path)
    state.save_videos([{"video_id": f"v{i}", "title": "", "description": f"twitch.tv/{ch}",
                        "create_time": 1, "cover": None, "share_url": None, "views": v,
                        "likes": 0, "comments": 0, "shares": 0, "duration": 20, "clip_id": None}
                       for i, (ch, v) in enumerate([("top", 5000), ("top", 6000), ("top", 5500),
                                                    ("flop", 50), ("flop", 40), ("flop", 60),
                                                    ("mid", 900), ("mid", 1000)])])
    for i in range(3):
        state.record(f"r{i}", "rejete", "rejected")
    good, bad = proven_channels(state)
    assert good == ["top"] and "flop" in bad and "rejete" in bad
