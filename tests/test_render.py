import shutil
import subprocess

import pytest

from clipbot.render import build_filter, probe_duration, render_vertical
from clipbot.subtitles import Word, write_ass

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")


@pytest.mark.parametrize("layout", ["blur", "crop", "split"])
def test_filter_ends_with_v(layout):
    assert build_filter(layout).endswith("[v]")
    assert "ass='/tmp/a\\:b.ass'[v]" in build_filter(layout, "/tmp/a:b.ass")


def test_filter_custom_crops():
    assert "crop=320:228:1600:0," in build_filter("split", cam_box=(320, 228, 1600, 0))
    assert "'min(max((0.2500)*iw-540,0),iw-1080)'" in build_filter("crop", crop_center=0.25)


@needs_ffmpeg
@pytest.mark.parametrize("layout,extra", [
    ("blur", {}), ("crop", {}), ("split", {}),
    ("crop", {"crop_center": 0.1}), ("split", {"cam_box": (320, 228, 1600, 40)}),
])
def test_render_produces_1080x1920(tmp_path, layout, extra):
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
        check=True,
    )
    subs = write_ass([Word("Salut", 0, .8), Word("Twitch", .8, 1.6)], tmp_path / "s.ass")
    out = render_vertical(src, tmp_path / "out.mp4", layout=layout, subtitles=subs,
                         **extra)
    dims = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert dims == "1080,1920"
    assert abs(probe_duration(out) - 2) < 0.3


def test_track_expr_interpolates():
    from clipbot.render import track_expr

    expr = track_expr([(0.0, 0.2), (2.0, 0.6)])
    for t, want in ((-1, 0.2), (0, 0.2), (1, 0.4), (2, 0.6), (5, 0.6)):
        got = eval(expr.replace("if(", "_if(").replace("lt(", "_lt("),
                   {"_if": lambda c, a, b: a if c else b, "_lt": lambda a, b: a < b, "t": t})
        assert abs(got - want) < 1e-3


@needs_ffmpeg
def test_render_follows_face(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=1920x1080:rate=30:duration=2", "-c:v", "libx264", str(src)],
                   check=True)
    out = render_vertical(src, tmp_path / "out.mp4", layout="crop",
                          crop_track=[(0.0, 0.2), (1.0, 0.5), (2.0, 0.8)])
    assert abs(probe_duration(out) - 2) < 0.3
