"""Accroche, début coupé, sous-titres déjà présents, sélection des clips."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from clipbot.enhance import MAX_TRIM, find_start, has_burned_subtitles, hook_text
from clipbot.subtitles import Word

SR = 16000


def test_hook_text():
    assert hook_text("Billy se fait daronned par la maman d'Ilhan 😭") == \
        "BILLY SE FAIT DARONNED PAR LA MAMAN…"
    assert hook_text("bisous sur la calvitie") == "BISOUS SUR LA CALVITIE"
    assert hook_text("😂😂") == "" and hook_text("lol") == ""
    assert hook_text("regarde ça #fyp https://x.y") == "REGARDE ÇA"


def tone(seconds, amp):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_find_start_cuts_slow_intro():
    audio = np.concatenate([tone(3, 0.005), tone(12, 0.5)])
    assert 2.4 <= find_start(audio, SR) <= 2.8


def test_find_start_keeps_fast_clip_and_limits():
    assert find_start(np.concatenate([tone(0.2, 0.01), tone(12, 0.5)]), SR) == 0.0
    long_intro = np.concatenate([tone(9, 0.005), tone(12, 0.5)])
    assert find_start(long_intro, SR) == MAX_TRIM
    short = np.concatenate([tone(3, 0.005), tone(6, 0.5)])  # garde au moins 8 s
    assert find_start(short, SR) <= 1.0 + 1e-6
    # la parole compte aussi : on ne coupe pas avant le premier mot
    quiet_talk = np.concatenate([tone(3, 0.005), tone(12, 0.5)])
    assert find_start(quiet_talk, SR, [Word("salut", 1.0, 1.4)]) == 0.7


def make_video(path, texts):
    cv2 = pytest.importorskip("cv2")
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (960, 540))
    for i in range(160):
        frame = np.full((540, 960, 3), 60, np.uint8)
        cv2.rectangle(frame, ((i * 7) % 800, 100), ((i * 7) % 800 + 120, 220), (200, 120, 40), -1)
        text = texts[(i // 20) % len(texts)]
        size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)[0]
        x = (960 - size[0]) // 2
        cv2.putText(frame, text, (x, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 6)
        cv2.putText(frame, text, (x, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        out.write(frame)
    out.release()
    return path


def test_burned_subtitles(tmp_path):
    subs = make_video(tmp_path / "subs.mp4", ["alors la on part sur une strat",
                                              "non mais regarde il est fou", "je te jure",
                                              "attends il arrive derriere",
                                              "oh le monstre triple kill", "pas possible"])
    hud = make_video(tmp_path / "hud.mp4", ["HEALTH 100 AMMO 30 ROUND 12"])
    assert has_burned_subtitles(subs) is True
    assert has_burned_subtitles(hud) is False


def test_standout_score_prefers_exceptional_clip():
    from clipbot.discover import standout_score
    from clipbot.twitch import Clip

    now = datetime.now(timezone.utc) - timedelta(hours=10)

    def clip(cid, name, views):
        return Clip(id=cid, url="u", title="t", broadcaster_name=name, creator_name="c",
                    view_count=views, created_at=now, duration=30)

    clips = [clip("big1", "gros", 5000), clip("big2", "gros", 5200), clip("big3", "gros", 5100),
             clip("small1", "petit", 40), clip("small2", "petit", 50), clip("star", "petit", 3000)]
    score = standout_score(clips)
    assert score(clips[-1]) > score(clips[0])  # le clip qui explose chez le petit streamer


def test_find_end_cuts_dead_tail():
    from clipbot.enhance import find_end

    audio = np.concatenate([tone(10, 0.5), tone(8, 0.005)])  # 10 s d'action, 8 s de vide
    end = find_end(audio, SR)
    assert 10.5 <= end <= 11.5
    assert find_end(tone(12, 0.5), SR) is None  # rien à couper
    assert find_end(audio, SR, [Word("mdr", 15.0, 15.5)]) is None  # parle jusqu'à la fin


def test_peak_time():
    from clipbot.enhance import peak_time

    audio = np.concatenate([tone(5, 0.05), tone(1, 0.9), tone(6, 0.05)])
    at, strength = peak_time(audio, SR)
    assert 4.5 <= at <= 6 and strength > 8


def test_punch_zoom_filter():
    from clipbot.render import build_filter

    graph = build_filter("crop", "/tmp/s.ass", punch_at=4.8)
    assert "between(t,4.80,5.30)" in graph and "eval=frame" in graph
    assert graph.index("eval=frame") < graph.index("ass=")  # zoom avant les sous-titres


def test_call_to_action():
    from clipbot.captions import call_to_action, format_caption

    assert call_to_action("😂", "a").endswith(("😭", "👇"))
    assert call_to_action("", "x") == call_to_action("", "x")  # stable pour un clip
    assert "👇" in format_caption("Il hurle", ["fyp"], "kamet0") or \
        "?" in format_caption("Il hurle", ["fyp"], "kamet0").splitlines()[1]
    assert format_caption("Vous auriez fait quoi ?", [], "k").splitlines()[1].startswith("🎮")
