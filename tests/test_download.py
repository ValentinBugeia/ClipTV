import pytest

from clipbot import download


def test_retries_when_clip_has_no_sound(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(url, dest, clip_id, fmt):
        calls.append(fmt)
        path = dest / f"{clip_id}.mp4"
        path.write_text(fmt)
        return path

    monkeypatch.setattr(download, "_fetch", fake_fetch)
    monkeypatch.setattr(download, "has_audio", lambda p: p.read_text() == "bv*+ba/b")
    path = download.download_clip("https://clips.twitch.tv/x", tmp_path, "x")
    assert calls == list(download.FORMATS) and path.read_text() == "bv*+ba/b"


def test_silent_clip_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "_fetch",
                        lambda url, dest, cid, fmt: (dest / f"{cid}.mp4").write_text("x")
                        or dest / f"{cid}.mp4")
    monkeypatch.setattr(download, "has_audio", lambda p: False)
    with pytest.raises(RuntimeError, match="sans son"):
        download.download_clip("https://clips.twitch.tv/x", tmp_path, "x")
