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


@needs_ffmpeg
@pytest.mark.parametrize("layout", ["blur", "crop", "split"])
def test_render_produces_1080x1920(tmp_path, layout):
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
        check=True,
    )
    subs = write_ass([Word("Salut", 0, .8), Word("Twitch", .8, 1.6)], tmp_path / "s.ass")
    out = render_vertical(src, tmp_path / "out.mp4", layout=layout, subtitles=subs)
    dims = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert dims == "1080,1920"
    assert abs(probe_duration(out) - 2) < 0.3
