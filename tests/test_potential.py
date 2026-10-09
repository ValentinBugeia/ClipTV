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


def test_start_score_without_history(tmp_path):
    state = make_state(tmp_path)
    hist = potential.history(state)
    strong = potential.score({"channel": "a", "signals": sig(vph=2000, standout=4)}, hist)
    weak = potential.score({"channel": "a", "signals": sig(vph=2, duration=58, speech=False,
                                                            hook=False, standout=0.4)}, hist)
    assert strong["note"] >= 8 and weak["note"] < 4 and weak["rarity"] == "common"
    assert any("Estimation de départ" in r for r in strong["reasons"])


def add_videos(state, items):
    state.save_videos([{"video_id": f"v{i}", "title": "", "description": desc,
                        "create_time": 1, "cover": None, "share_url": None, "views": views,
                        "likes": 0, "comments": 0, "shares": 0, "duration": 20, "clip_id": None}
                       for i, (desc, views) in enumerate(items)])


def test_score_from_account_history(tmp_path):
    state = make_state(tmp_path)
    # nico_la : ~4000 vues ; autres : ~500 vues (reconnus par le lien twitch.tv/…)
    add_videos(state, [("a 🎙️ twitch.tv/nico_la #justchatting", 4000),
                       ("b twitch.tv/nico_la", 3800), ("c twitch.tv/nico_la", 4200),
                       ("d twitch.tv/autre", 500), ("e twitch.tv/autre", 450),
                       ("f twitch.tv/autre", 520), ("g twitch.tv/zz", 600)])
    hist = potential.history(state)
    star = potential.score({"channel": "nico_la", "signals": sig()}, hist)
    other = potential.score({"channel": "autre", "signals": sig()}, hist)
    new = potential.score({"channel": "inconnu", "signals": sig()}, hist)
    assert star["note"] > new["note"] > other["note"]
    assert 4.5 <= new["note"] <= 5.5  # streamer jamais publié : « comme d'habitude »
    assert any("Tes 3 TikTok de nico_la" in r for r in star["reasons"])
    assert any("Vues attendues" in r for r in star["reasons"])


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


def test_backfill_old_clips(tmp_path):
    import subprocess

    cfg = Config()
    cfg.data_dir = tmp_path
    cfg.twitch_client_id = cfg.twitch_client_secret = None
    state = State(cfg.db_path)
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:duration=4", "-pix_fmt", "yuv420p", str(video)],
                   check=True)
    state.record("old", "nico_la", "rendered", output_path=str(video))
    assert potential.backfill(cfg, state) == 1
    sig = json.loads(state.get("old")["signals"])
    assert 3.5 <= sig["duration"] <= 4.5
    assert potential.backfill(cfg, state) == 0  # déjà fait


def test_score_survives_text_where_number_expected(tmp_path):
    """Ancienne version : « reaction » contenait le type du Radar (« laugh »)."""
    state = make_state(tmp_path)
    hist = potential.history(state)
    clip = {"channel": "a", "signals": sig(reaction="laugh", peak_at=2, jury="8")}
    assert 0 <= potential.score(clip, hist)["note"] <= 10
