"""@ TikTok des streamers dans la description."""

from types import SimpleNamespace

from clipbot import socials
from clipbot.config import Config
from clipbot.state import State


def make_state(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    return State(cfg.db_path)


def test_find_handle_in_texts():
    assert socials.find_in_text("https://www.tiktok.com/@Nico.La?lang=fr") == "nico.la"
    assert socials.find_in_text("Mon TikTok : @nicola_off") == "nicola_off"
    assert socials.find_in_text("Instagram @nico") is None


def test_handle_cache_and_manual(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    calls = []
    monkeypatch.setattr(socials, "lookup", lambda login: calls.append(login) or "nicotok")
    assert socials.tiktok_handle(state, "Nico_La") == "nicotok"
    assert socials.tiktok_handle(state, "nico_la") == "nicotok" and calls == ["nico_la"]  # en cache
    socials.save_manual(state, "nico_la @vraicompte\nkamet0 -")
    assert socials.tiktok_handle(state, "nico_la") == "vraicompte"
    assert socials.tiktok_handle(state, "kamet0") is None and calls == ["nico_la"]
    assert "nico_la @vraicompte" in socials.as_lines(state) and "kamet0 -" in socials.as_lines(state)


def test_lookup_failure_never_blocks(tmp_path, monkeypatch):
    state = make_state(tmp_path)

    def boom(login):
        raise OSError("réseau")

    monkeypatch.setattr(socials, "lookup", boom)
    assert socials.tiktok_handle(state, "x") is None


def test_caption_mentions_streamer():
    from clipbot.captions import format_caption
    from clipbot.pipeline import Options, template_caption

    clip = SimpleNamespace(id="c", title="Il hurle", broadcaster_name="Nico_La",
                           creator_name="x", category="", tiktok_handle="nicotok")
    assert "twitch.tv/nico_la · @nicotok" in template_caption(Options().caption_template, clip)
    clip.tiktok_handle = None
    assert "@" not in template_caption(Options().caption_template, clip)
    assert "twitch.tv/nico_la · @nicotok" in format_caption("Il hurle", [], "Nico_La", tiktok="nicotok")
