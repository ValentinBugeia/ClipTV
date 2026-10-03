from clipbot.subtitles import Word, build_ass, group_words, _ass_color, _ts


def words(*items):
    return [Word(t, s, e) for t, s, e in items]


def test_group_by_max_words():
    w = words(("a", 0, .2), ("b", .2, .4), ("c", .4, .6), ("d", .6, .8))
    assert [[x.text for x in g] for g in group_words(w)] == [["a", "b", "c"], ["d"]]


def test_group_splits_on_pause_and_sentence_end():
    w = words(("Salut.", 0, .3), ("ça", .35, .5), ("va", .5, .7), ("bien", 2.0, 2.3))
    assert [[x.text for x in g] for g in group_words(w)] == [["Salut."], ["ça", "va"], ["bien"]]


def test_timestamp_and_color():
    assert _ts(3725.456) == "1:02:05.46"
    assert _ass_color("#FFE600") == "&H0000E6FF"


def test_build_ass_highlights_each_word():
    ass = build_ass(words(("non", 0, .3), ("mais", .3, .6)), highlight="#FF0000")
    dialogues = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogues) == 2
    assert "{\\c&H000000FF}NON{\\c&H00FFFFFF&} MAIS" in dialogues[0]
    assert "NON {\\c&H000000FF}MAIS" in dialogues[1]
    # le premier mot reste affiché jusqu'au début du second
    assert dialogues[0].split(",")[1:3] == ["0:00:00.00", "0:00:00.30"]


def test_braces_are_escaped():
    ass = build_ass(words(("{evil}", 0, .5)))
    assert "{evil}" not in ass and "(EVIL)" in ass


def test_load_audio_with_ffmpeg(tmp_path):
    import shutil
    import subprocess

    import pytest

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg absent")
    np = pytest.importorskip("numpy")
    from clipbot.subtitles import SAMPLE_RATE, load_audio

    src = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x240:duration=2", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264",
                    "-c:a", "aac", str(src)], check=True)
    audio = load_audio(src)
    assert audio.dtype == np.float32 and abs(len(audio) / SAMPLE_RATE - 2) < 0.1
    assert 0.05 < float(abs(audio).max()) <= 1.0
