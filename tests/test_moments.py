"""Moments : un clip complet découpé dans la rediffusion autour du clip Twitch."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from clipbot import moments
from clipbot.moments import Window
from clipbot.subtitles import Word


def clip(cid, video="v1", offset=100.0, duration=20.0):
    return SimpleNamespace(id=cid, title=cid, video_id=video, vod_offset=offset,
                           duration=duration, url="u")


def test_clips_of_the_same_moment_are_merged():
    a, b, c = clip("a", offset=100), clip("b", offset=110), clip("c", offset=300)
    d = clip("d", video="", offset=None)
    kept = moments.merge_moments([(a, "x"), (b, "x"), (c, "x"), (d, "x")])
    assert [k.id for k, _ in kept] == ["a", "c", "d"] and a.clippers == 2


def words(*items):
    return [Word(t, s, e) for t, s, e in items]


def test_auto_cut_starts_with_the_sentence_and_ends_after_it():
    # extrait de 50 s, clip Twitch de 15 à 35 s qui démarre et finit en pleine phrase
    w = Window(Path("x"), 85.0, 50.0, (15.0, 35.0))
    said = words(("bon", 2.0, 2.4), ("alors", 11.0, 11.4), ("tu", 11.5, 11.7),
                 ("vois", 11.8, 12.2), ("ce", 12.5, 12.7), ("truc", 12.9, 16.0),
                 ("non", 20.0, 20.5), ("mais", 33.0, 33.5), ("attends", 33.6, 37.0),
                 ("quoi", 37.2, 38.0), ("plus", 45.0, 45.5))
    start, end = moments.auto_cut(w, said)
    assert 10 <= start <= 11.0   # début de « alors tu vois ce truc », pas 15 s
    assert 38.0 <= end <= 39.5   # fin de « mais attends quoi », pas 35 s
    assert start < 15 and end > 35


def test_auto_cut_keeps_the_reaction_sound():
    sr = 16000
    w = Window(Path("x"), 0.0, 40.0, (5.0, 25.0))
    audio = np.full(40 * sr, 0.01, dtype=np.float32)
    audio[25 * sr:29 * sr] = 0.5  # fou rire non transcrit juste après le clip
    start, end = moments.auto_cut(w, words(("ah", 24.0, 24.8)), audio, sr)
    assert end >= 29.0


def test_cut_limits():
    w = Window(Path("x"), 0.0, 90.0, (20.0, 40.0))
    assert moments.clamp_cut(w, 0, 90) == (30.0, 90.0)       # 60 s max, fin gardée
    s, e = moments.clamp_cut(w, 29, 31)                        # 10 s min
    assert e - s >= 10
    assert moments.clamp_cut(w, -5, 20) == (0.0, 20.0)


def test_timed_lines_for_claude():
    text = moments.timed_lines(words(("salut", 1.0, 1.4), ("toi", 1.5, 1.9),
                                     ("quoi", 5.0, 5.5)))
    assert text == "[1.0 → 1.9] salut toi\n[5.0 → 5.5] quoi"


def test_radar_cut_replaces_auto_cut():
    from clipbot import selection

    c = clip("a")
    c.window = Window(Path("x"), 85.0, 50.0, (15.0, 35.0))
    c.cut = (14.0, 36.0)
    selection._radar_cut(c, {"start": 9.5, "end": 41.0})
    assert c.cut == (9.5, 41.0)
    selection._radar_cut(c, {"start": 9.5, "end": 10.0})  # absurde : ignoré
    assert c.cut == (9.5, 41.0)


def test_final_video_from_rebroadcast_is_realigned(monkeypatch, tmp_path):
    sr = 16000
    rng = np.random.default_rng(3)
    env = np.repeat(rng.random(50 * 4) ** 3, sr // 4)
    small = (rng.standard_normal(len(env)) * 0.1 * env).astype(np.float32)  # extrait
    window_path = tmp_path / "a-win.mp4"
    window_path.write_bytes(b"x")
    c = clip("a")
    c.window = Window(window_path, 85.0, 50.0, (15.0, 35.0))
    c.cut = (10.0, 40.0)
    asked = []

    def fake_range(video_id, start, end, target, fmt):
        asked.append((round(start, 1), round(end, 1)))
        target.write_bytes(b"y")
        return target
    # la version 1080p commence 1,3 s plus tôt que demandé (image clé)
    big = small[int((10.0 - moments.PAD - 1.3) * sr):int((40.0 + moments.PAD) * sr)]
    monkeypatch.setattr(moments, "_vod_range", fake_range)
    monkeypatch.setattr("clipbot.subtitles.load_audio",
                        lambda p: small if Path(p) == window_path else big)
    out = moments.final_video(c, tmp_path)
    assert out == tmp_path / "a.mp4"
    assert asked == [(85 + 10 - moments.PAD, 85 + 40 + moments.PAD)]
    start, length = c.render_cut
    assert abs(start - (moments.PAD + 1.3)) < 0.1 and length == 30.0
    assert not window_path.exists()  # extrait léger supprimé


def test_final_video_without_rebroadcast_cuts_inside_the_clip(monkeypatch, tmp_path):
    c = clip("a", video="", offset=None)
    preview = tmp_path / "a-small.mp4"
    preview.write_bytes(b"x")
    c.window = Window(preview, None, 30.0, (0.0, 30.0))
    c.cut = (2.0, 27.0)
    monkeypatch.setattr("clipbot.download.download_clip",
                        lambda url, d, cid, *a: d / f"{cid}.mp4")
    assert moments.final_video(c, tmp_path) == tmp_path / "a.mp4"
    assert c.render_cut == (2.0, 25.0)
