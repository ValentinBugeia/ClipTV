"""Accroche, début coupé, sous-titres déjà présents, sélection des clips."""


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


def test_question_matches_clip():
    from types import SimpleNamespace

    from clipbot.captions import CTAS, GENERIC_CTAS, format_caption, title_mood
    from clipbot.pipeline import Options, template_caption

    assert title_mood("Il a eu tellement peur") == "😱"
    assert title_mood("Une crise de nerfs ? non, une critique") == ""  # pas « cri »
    assert title_mood("Il face la caméra") == ""                        # pas « ace »
    # titre neutre : question qui va avec n'importe quel clip, jamais une ambiance au hasard
    for i in range(30):
        clip = SimpleNamespace(id=f"c{i}", title="Partie classée avec les potes",
                               broadcaster_name="nico", creator_name="x", category="Valorant")
        assert template_caption(Options().caption_template, clip).splitlines()[1] in GENERIC_CTAS
    scary = SimpleNamespace(id="s", title="Le jumpscare de fou", broadcaster_name="nico",
                            creator_name="x", category="")
    assert template_caption(Options().caption_template, scary).splitlines()[1] in CTAS["😱"]
    # légende écrite par Claude : sa question, liée au contenu du clip
    text = format_caption("Il découvre son score", ["fyp"], "nico",
                          question="Tu t'attendais à ce score ? 👇")
    assert text.splitlines()[1] == "Tu t'attendais à ce score ? 👇"


def test_reaction_emoji():
    from clipbot.enhance import reaction_emoji
    from clipbot.subtitles import Word

    assert reaction_emoji([Word("mdrrr", 5.0, 5.4)], 5.2).stem == "laugh"
    assert reaction_emoji([Word("aaaah", 3.0, 3.5)], 3.1).stem == "scream"
    assert reaction_emoji([Word("bonjour", 3.0, 3.5)], 3.1, "Le jumpscare de fou").stem == "scream"
    assert reaction_emoji([Word("bonjour", 3.0, 3.5)], 3.1, "Partie classée") is None
    assert reaction_emoji([Word("mdr", 20.0, 20.4)], 3.1) is None  # trop loin de la réaction


def test_emoji_filter_and_render(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path

    from clipbot.render import build_filter, probe_duration, render_vertical

    graph = build_filter("crop", None, emoji_at=2.0)
    assert "[1:v]" in graph and "between(t,2.00,3.20)" in graph and graph.endswith("[v]")
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg absent")
    src = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:duration=3", "-f", "lavfi", "-i",
                    "sine=duration=3", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
    emoji = Path(__file__).parent.parent / "clipbot" / "emoji" / "laugh.png"
    out = render_vertical(src, tmp_path / "o.mp4", layout="blur", emoji=emoji, emoji_at=1.0)
    assert 2.5 <= probe_duration(out) <= 3.5  # l'image en boucle ne prolonge pas la vidéo


def test_same_behaviour_on_any_pc(monkeypatch):
    """Même un PC très lent : le Radar écoute toujours les paroles (pas d'adaptation)."""
    from pathlib import Path

    from clipbot import jury, subtitles
    from clipbot.subtitles import Word

    monkeypatch.setattr(subtitles, "speed", {"base": 0.1, "small": 0.05})
    monkeypatch.setattr(subtitles, "transcribe", lambda *a, **k: [Word("salut", 0, 1)])
    assert [w.text for w in jury.quick_transcript(Path("x.mp4"))] == ["salut"]


def test_burned_subtitles_kept_above_tiktok_caption():
    from clipbot.render import build_filter

    crop = build_filter("crop", None, safe_bottom=400)
    assert "scale=1080:1520" in crop and "overlay=0:0" in crop   # image utile en haut
    split = build_filter("split", None, cam_height=700, safe_bottom=400)
    assert "scale=1080:820" in split and "split=3" in split       # jeu raccourci de 400 px
    assert "overlay" not in build_filter("crop", None)            # sans sous-titres incrustés
    assert build_filter("blur", None, safe_bottom=400) == build_filter("blur", None)


def test_find_end_keeps_quiet_reaction_and_last_words():
    from clipbot.enhance import find_end
    from clipbot.subtitles import Word

    talk, laugh, silence = tone(8, 0.5), tone(3, 0.1), tone(2, 0.002)  # rire à 20 % du niveau
    audio = np.concatenate([talk, laugh, silence])
    assert find_end(audio, SR) is None                     # pas 3 s de silence : on ne coupe pas
    long_silence = np.concatenate([talk, laugh, tone(6, 0.002)])
    end = find_end(long_silence, SR)
    assert end is not None and end >= 11 + 1.4             # le rire et sa marge sont gardés
    # dernier mot repéré tard (transcription) : jamais coupé avant
    assert find_end(long_silence, SR, [Word("fin", 13.0, 13.6)]) is None


def test_clip_found_in_rebroadcast_audio():
    """Le clip est retrouvé (et aligné) dans l'extrait de la rediffusion par son son."""
    import numpy as np

    from clipbot.download import locate

    rng = np.random.default_rng(1)
    sr = 16000
    env = np.repeat(rng.random(70 * 4) ** 3, sr // 4)
    long = (rng.standard_normal(len(env)) * 0.1 * env).astype(np.float32)
    clip = long[int(12.3 * sr):int(42.3 * sr)] * 0.5  # volume différent : pas grave
    assert locate(clip, long, sr) == 12.3
    other = (rng.standard_normal(30 * sr) * 0.1 *
             np.repeat(rng.random(120) ** 3, sr // 4)).astype(np.float32)
    assert locate(other, long, sr) is None


def test_without_nvidia_everything_runs_on_the_processor(monkeypatch):
    """PC sans carte NVIDIA (ou bibliothèques absentes) : processeur, comme avant."""
    from clipbot import gpu

    gpu.cuda_libraries.cache_clear()
    monkeypatch.setattr(gpu, "_cuda_device", lambda: True)  # carte vue…
    monkeypatch.setattr(gpu, "_search_path", lambda: [])   # …mais pas les bibliothèques
    assert gpu.whisper_device("auto") == "cpu"
    gpu.cuda_libraries.cache_clear()
    monkeypatch.setattr(gpu, "_nvenc_works", lambda: False)
    assert "libx264" in gpu.video_encoder()


def test_render_falls_back_to_processor_when_nvenc_fails(monkeypatch, tmp_path):
    import subprocess

    from clipbot import gpu, render

    monkeypatch.setattr(gpu, "_nvenc_works", lambda: True)
    monkeypatch.setattr(gpu, "_disabled", set())
    used = []

    def fake_run(cmd, dst):
        used.append(cmd[cmd.index("-c:v") + 1])
        if used[-1] == "h264_nvenc":
            raise subprocess.CalledProcessError(1, cmd, stderr="No NVENC capable devices")
    monkeypatch.setattr(render, "_run_interruptible", fake_run)
    render.render_vertical(tmp_path / "in.mp4", tmp_path / "out.mp4", layout="blur")
    assert used == ["h264_nvenc", "libx264"]
    assert gpu.video_encoder()[1] == "libx264"  # plus d'essai sur la carte ensuite
