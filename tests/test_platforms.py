import json
import time

from clipbot.instagram import InstagramClient, reels_caption
from clipbot.youtube import YouTubeClient, shorts_metadata


class Resp:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload or {}, status, headers or {}
        self.ok = status < 400
        self.text = json.dumps(self.payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def _next(self, method, url, **kw):
        if "data" in kw and hasattr(kw["data"], "read"):
            kw["data"] = kw["data"].read()
        self.calls.append((method, url, kw))
        return self.responses.pop(0)

    def get(self, url, **kw):
        return self._next("GET", url, **kw)

    def post(self, url, **kw):
        return self._next("POST", url, **kw)

    def put(self, url, **kw):
        return self._next("PUT", url, **kw)


def test_shorts_metadata():
    title, desc, tags = shorts_metadata("Il rage <vraiment> 😂 #fyp\n🎮 twitch.tv/kamet0\n#twitch #lol")
    assert title == "Il rage vraiment 😂 #Shorts"
    assert "<" not in desc and desc.endswith("#Shorts")
    assert tags == ["fyp", "twitch", "lol", "Shorts"]
    long_title, _, _ = shorts_metadata("a" * 300)
    assert len(long_title) <= 100 and long_title.endswith("#Shorts")


def test_youtube_refresh_and_upload(tmp_path):
    token = tmp_path / "yt.json"
    token.write_text(json.dumps({"access_token": "old", "refresh_token": "r",
                                 "expires_in": 3600, "obtained_at": 0}))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    session = FakeSession([
        Resp({"access_token": "new", "expires_in": 3600}),           # refresh
        Resp(headers={"Location": "https://upload/session"}),        # init resumable
        Resp({"id": "abc123"}),                                      # upload
    ])
    yt = YouTubeClient("id", "secret", token, session=session)
    assert yt.upload(video, caption="Énorme clip #fyp", privacy="unlisted") == "abc123"

    _, _, init = session.calls[1]
    assert init["json"]["status"]["privacyStatus"] == "unlisted"
    assert init["json"]["snippet"]["categoryId"] == "20"
    assert init["headers"]["Authorization"] == "Bearer new"
    assert init["headers"]["X-Upload-Content-Length"] == "5"
    assert session.calls[2][1] == "https://upload/session" and session.calls[2][2]["data"] == b"video"
    saved = json.loads(token.read_text())
    assert saved["access_token"] == "new" and saved["refresh_token"] == "r"


def test_reels_caption_limits_hashtags():
    caption = "hook " + " ".join(f"#t{i}" for i in range(40))
    assert reels_caption(caption).count("#") == 30


def test_instagram_publish_reel(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    token = tmp_path / "ig.json"
    token.write_text(json.dumps({"access_token": "tok", "user_id": "42",
                                 "obtained_at": int(time.time())}))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"reel")
    session = FakeSession([
        Resp({"id": "c1", "uri": "https://rupload.facebook.com/ig-api-upload/c1"}),
        Resp({"success": True}),
        Resp({"status_code": "IN_PROGRESS"}),
        Resp({"status_code": "FINISHED"}),
        Resp({"id": "media9"}),
    ])
    ig = InstagramClient(token, session=session)
    assert ig.publish_reel(video, caption="hook #fyp") == "media9"

    method, url, kw = session.calls[0]
    assert url.endswith("/42/media") and kw["params"]["media_type"] == "REELS"
    assert kw["params"]["upload_type"] == "resumable"
    _, url, kw = session.calls[1]
    assert url.startswith("https://rupload.facebook.com/")
    assert kw["headers"]["file_size"] == "4" and kw["headers"]["Authorization"] == "OAuth tok"
    assert session.calls[4][2]["params"]["creation_id"] == "c1"


def test_instagram_error_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    token = tmp_path / "ig.json"
    token.write_text(json.dumps({"access_token": "tok", "user_id": "42",
                                 "obtained_at": int(time.time())}))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"reel")
    session = FakeSession([
        Resp({"id": "c1", "uri": "https://rupload.facebook.com/x"}),
        Resp({"success": True}),
        Resp({"status_code": "ERROR", "status": "format invalide"}),
    ])
    try:
        InstagramClient(token, session=session).publish_reel(video, caption="x")
    except RuntimeError as exc:
        assert "format invalide" in str(exc)
    else:
        raise AssertionError("une erreur était attendue")
