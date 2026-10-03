import threading
import urllib.error
import urllib.request

import pytest

from clipbot.config import Config
from clipbot.pipeline import Options
from clipbot.review import make_server
from clipbot.state import State


@pytest.fixture()
def server(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    video = tmp_path / "v.mp4"
    video.write_bytes(bytes(range(256)) * 4)
    state = State(cfg.db_path)
    state.record("abc", "kamet0", "rendered", title="<b>Énorme</b>", url="https://x",
                 view_count=42, output_path=str(video), caption="légende #fyp")
    srv = make_server(cfg, Options(), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", state
    srv.shutdown()


def test_list_page_escapes_and_shows_clip(server):
    base, _ = server
    body = urllib.request.urlopen(base + "/").read().decode()
    assert "&lt;b&gt;Énorme&lt;/b&gt;" in body and "légende #fyp" in body
    assert "À valider (1)" in body


def test_video_range(server):
    base, _ = server
    req = urllib.request.Request(base + "/video/abc", headers={"Range": "bytes=10-19"})
    resp = urllib.request.urlopen(req)
    assert resp.status == 206 and resp.read() == bytes(range(10, 20))
    assert resp.headers["Content-Range"] == "bytes 10-19/1024"


def test_reject(server):
    base, state = server
    data = "caption=nouvelle+l%C3%A9gende".encode()
    urllib.request.urlopen(urllib.request.Request(base + "/reject/abc", data=data))
    row = state.get("abc")
    assert row["status"] == "rejected" and row["caption"] == "nouvelle légende"
