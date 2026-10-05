"""Indicateur de potentiel et clips déjà présents sur le compte TikTok."""

import json
import time
from datetime import datetime, timezone

from clipbot import potential, stats
from clipbot.config import Config
from clipbot.state import State
from clipbot.twitch import Clip


def make_state(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    return State(cfg.db_path)


def sig(**kw):
    return json.dumps({"vph": 50, "duration": 25, "speech": True, "hook": True, **kw})


def test_score_levels_without_history(tmp_path):
    state = make_state(tmp_path)
    hist = potential.history(state)
    strong = potential.score({"channel": "a", "signals": sig(vph=2000, standout=4)}, hist)
    weak = potential.score({"channel": "a", "signals": sig(vph=2, duration=58, speech=False,
                                                            hook=False, standout=0.4)}, hist)
    assert strong["level"] == "fort" and weak["level"] == "faible"
    assert any("Pas encore assez" in r for r in strong["reasons"])


def test_score_uses_account_history(tmp_path):
    state = make_state(tmp_path)
    videos = []
    for i in range(6):  # streamer « star » : ses clips font 10x plus de vues chez toi
        channel = "star" if i < 3 else "autre"
        state.record(f"c{i}", channel, "published", category="Valorant")
        videos.append({"video_id": f"v{i}", "title": "", "description": "", "create_time": 1,
                       "cover": None, "share_url": None, "views": 5000 if i < 3 else 500,
                       "likes": 0, "comments": 0, "shares": 0, "duration": 20,
                       "clip_id": f"c{i}"})
    state.save_videos(videos)
    hist = potential.history(state)
    star = potential.score({"channel": "star", "signals": sig()}, hist)
    other = potential.score({"channel": "autre", "signals": sig()}, hist)
    assert star["score"] > other["score"]
    assert any("marchent bien" in r for r in star["reasons"])


def test_on_tiktok_detects_existing_video(tmp_path):
    state = make_state(tmp_path)
    state.save_videos([{"video_id": "v1", "title": "",
                        "description": "Billy se fait daronned par la maman d'Ilhan 😭\n"
                                       "🎙️ twitch.tv/nico_la\n#nico_la #twitchfr",
                        "create_time": int(time.time()), "cover": None, "share_url": None,
                        "views": 10, "likes": 0, "comments": 0, "shares": 0, "duration": 30,
                        "clip_id": None}])
    check = stats.on_tiktok(state)

    def clip(cid, title, name="Nico_La"):
        return Clip(id=cid, url="u", title=title, broadcaster_name=name, creator_name="x",
                    view_count=1, created_at=datetime.now(timezone.utc), duration=30)

    assert check(clip("x1", "Billy se fait daronned par la maman d'Ilhan"))
    assert not check(clip("x2", "Un tout autre moment du stream"))
    # légende réécrite par Claude : mêmes mots-clés + même streamer
    state.save_videos([{"video_id": "v2", "title": "", "description":
                        "Quand la maman d'Ilhan débarque en plein live 😭 twitch.tv/nico_la "
                        "#billy #daronned", "create_time": 1, "cover": None, "share_url": None,
                        "views": 1, "likes": 0, "comments": 0, "shares": 0, "duration": 30,
                        "clip_id": None}])
    check = stats.on_tiktok(state)
    assert check(clip("x3", "Billy daronned maman Ilhan"))
    assert not check(clip("x4", "Billy daronned maman Ilhan", "autre_streamer"))
