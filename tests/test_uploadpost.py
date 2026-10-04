"""Publication TikTok en public via Upload-Post (faux serveur local)."""

import json
from email.parser import BytesParser
from email.policy import HTTP
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from clipbot.uploadpost import UploadPostClient, UploadPostError


def serve(routes):
    seen = []

    class H(BaseHTTPRequestHandler):
        def _reply(self, status, data):
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization"), None))
            self._reply(*routes["GET " + self.path.split("?")[0]])

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            msg = BytesParser(policy=HTTP).parsebytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
            fields = {}
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                value = part.get_filename() or part.get_payload(decode=True).decode()
                fields.setdefault(name, []).append(value)
            seen.append(("POST", self.path, self.headers.get("Authorization"), fields))
            self._reply(*routes["POST " + self.path])

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}/api", seen


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\0" * 1000)
    return p


def test_upload_public(video):
    base, seen = serve({"POST /api/upload": (200, {"success": True, "results": {
        "tiktok": {"success": True, "url": "https://tiktok.com/@x/video/1"}}})})
    ident = UploadPostClient("KEY", base).upload_tiktok(video, caption="Énorme #fyp",
                                                         user="cetaitenlive")
    assert ident == "https://tiktok.com/@x/video/1"
    method, path, auth, f = seen[0]
    assert auth == "Apikey KEY" and f["platform[]"] == ["tiktok"]
    assert f["privacy_level"] == ["PUBLIC_TO_EVERYONE"] and f["post_mode"] == ["DIRECT_POST"]
    assert f["user"] == ["cetaitenlive"] and f["video"] == ["clip.mp4"]


def test_upload_refused_by_tiktok(video):
    base, _ = serve({"POST /api/upload": (200, {"success": True, "results": {
        "tiktok": {"success": False, "error": "tiktok_privacy_unavailable"}}})})
    with pytest.raises(UploadPostError, match="tiktok_privacy_unavailable"):
        UploadPostClient("KEY", base).upload_tiktok(video, caption="x", user="u")


def test_bad_key(video):
    base, _ = serve({"POST /api/upload": (401, {"message": "Invalid API key"})})
    with pytest.raises(UploadPostError, match=r"\(401\).*Invalid API key"):
        UploadPostClient("BAD", base).upload_tiktok(video, caption="x", user="u")


def test_tiktok_account():
    base, _ = serve({"GET /api/uploadposts/users": (200, {"success": True, "profiles": [
        {"username": "cetaitenlive", "social_accounts": {
            "tiktok": {"display_name": "C'était En Live"}, "instagram": ""}}]})})
    client = UploadPostClient("KEY", base)
    assert client.tiktok_account("cetaitenlive") == "C'était En Live"
    with pytest.raises(UploadPostError, match="introuvable"):
        client.tiktok_account("autre")


def test_pipeline_uses_uploadpost(tmp_path, monkeypatch, video):
    from clipbot import pipeline
    from clipbot.config import Config
    from clipbot.state import State

    base, seen = serve({"POST /api/upload": (200, {"success": True, "request_id": "r1"})})
    monkeypatch.setenv("UPLOADPOST_API_KEY", "KEY")
    monkeypatch.setenv("UPLOADPOST_USER", "cetaitenlive")
    monkeypatch.setenv("UPLOADPOST_BASE_URL", base)
    cfg = Config()
    cfg.data_dir = tmp_path
    state = State(cfg.db_path)
    state.record("c1", "nico_la", "publishing", output_path=str(video), caption="légende")
    state.save_settings({pipeline.TIKTOK_MODE: "uploadpost"})
    errors = pipeline.publish_clip("c1", cfg, state, pipeline.Options(platforms=["tiktok"]))
    assert errors == [] and seen[0][3]["title"] == ["légende"]
    assert state.posts("c1")["tiktok"]["status"] == "ok"
