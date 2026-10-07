"""Sélection des clips : réaction forte et tôt, présélection, vidéos écartées supprimées."""

import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

from clipbot import selection


def make_clip(path, expr, seconds=20):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=160x90:d=%d" % seconds, "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=16000:d={seconds}", "-shortest", "-c:v", "libx264",
                    "-c:a", "aac", str(path)], check=True)
    return path


CALM = "0.05*sin(2*PI*200*t)"
EARLY = "if(between(t,2,4),0.8,0.05)*sin(2*PI*200*t)"
LATE = "if(between(t,16,18),0.8,0.05)*sin(2*PI*200*t)"


def test_audio_profile_and_factor(tmp_path):
    early = selection.audio_profile(make_clip(tmp_path / "e.mp4", EARLY))
    late = selection.audio_profile(make_clip(tmp_path / "l.mp4", LATE))
    calm = selection.audio_profile(make_clip(tmp_path / "c.mp4", CALM))
    assert early["reaction"] > 8 and 1.5 <= early["peak_at"] <= 4.5
    assert late["peak_at"] >= 15 and calm["reaction"] < 2
    assert selection.audio_factor(early) > selection.audio_factor(late) \
        > selection.audio_factor(calm)


def test_pick_best_keeps_strong_early_reaction(tmp_path):
    def clip(cid):
        return SimpleNamespace(id=cid, title=cid, created_at=datetime.now(timezone.utc))

    files = {"calm": make_clip(tmp_path / "calm.mp4", CALM),
             "late": make_clip(tmp_path / "late.mp4", LATE),
             "early": make_clip(tmp_path / "early.mp4", EARLY)}
    cands = [(clip("calm"), "a"), (clip("late"), "b"), (clip("early"), "c")]
    kept = selection.pick_best(cands, {k: (lambda p=p: p) for k, p in files.items()}, 1)
    assert [c.id for c, _ in kept] == ["early"]
    assert kept[0][0].audio["reaction"] > 8
    assert files["early"].exists() and not files["calm"].exists() and not files["late"].exists()


def test_preselection_factors():
    assert selection.duration_factor(25) > selection.duration_factor(55)
    assert selection.shortlist_size(3) == 9 and selection.shortlist_size(10) == 12
    clip = SimpleNamespace(broadcaster_name="Nico_La", category="")
    hist = {"all": [100, 120, 90, 110, 100, 1000, 900], "channel": {"nico_la": [1000, 900]},
            "category": {}}
    assert selection.history_factor(clip, hist) > 2
    assert selection.history_factor(clip, {"all": [1], "channel": {}, "category": {}}) == 1.0


def test_prefetch_wait_stops_on_cancel(monkeypatch):
    import threading
    import time

    import pytest

    from clipbot import progress
    from clipbot.pipeline import Prefetcher

    release = threading.Event()
    monkeypatch.setattr("clipbot.download.download_clip",
                        lambda url, d, cid: release.wait(5) and "fichier")
    clip = type("C", (), {"id": "c1", "url": "u"})()
    pre = Prefetcher(type("Cfg", (), {"downloads_dir": "/tmp"})(), [clip])
    progress.begin("test")
    threading.Timer(0.3, progress.cancel).start()
    t0 = time.time()
    with pytest.raises(progress.Cancelled):
        pre.source(clip)()  # téléchargement encore en cours : l'arrêt n'attend pas sa fin
    assert time.time() - t0 < 2
    progress.end("arrêtée")
    release.set()
    pre.close()
