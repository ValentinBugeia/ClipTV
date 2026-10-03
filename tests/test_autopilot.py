import time

from clipbot import autopilot as ap
from clipbot.config import Config
from clipbot.pipeline import Options
from clipbot.state import State


def make(tmp_path, **settings):
    cfg = Config()
    cfg.data_dir = tmp_path
    cfg.twitch_client_id = cfg.twitch_client_secret = "x"
    cfg.post_slots = ["12:00", "18:00"]
    state = State(cfg.db_path)
    state.save_settings({"enabled": True, "channels": ["a", "b"], "live_channels": [],
                         "top": 5, **settings})
    return cfg, state


def test_search_schedules_and_respects_queue_limit(tmp_path, monkeypatch):
    cfg, state = make(tmp_path, max_queue=3)
    calls = []

    def fake_run(channels, cfg, state, opts, twitch, *, hours, top, min_views):
        calls.append((channels[0], top, opts.schedule, opts.ai_caption))
        for i in range(top):  # simule des clips programmés
            state.record(f"{channels[0]}{i}", channels[0], "scheduled", scheduled_at=1)
        return [(f"{channels[0]}{i}", True) for i in range(top)]

    monkeypatch.setattr("clipbot.pipeline.run_channels", fake_run)
    pilot = ap.Autopilot(cfg, state, Options())
    pilot._step()
    # 3 places : 3 clips pour « a », plus rien pour « b »
    assert calls == [("a", 3, True, True)]
    assert "3 nouveau(x) clip(s) programmé(s)" in pilot.message

    pilot.force = True
    pilot._step()
    assert "File d'attente pleine" in pilot.message and len(calls) == 1


def test_disabled_does_nothing(tmp_path, monkeypatch):
    cfg, state = make(tmp_path, enabled=False)
    monkeypatch.setattr("clipbot.pipeline.run_channels",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    pilot = ap.Autopilot(cfg, state, Options())
    pilot._step()
    assert pilot.message == "En pause"


def test_settings_apply_to_config(tmp_path):
    cfg, state = make(tmp_path, platforms=["youtube"], post_slots=["09:00"])
    ap.apply_settings(cfg, ap.load_settings(state, cfg))
    assert cfg.platforms == ["youtube"] and cfg.post_slots == ["09:00"]
    assert ap.max_queue({"post_slots": ["09:00", "20:00"], "max_queue": 0}) == 4


def test_live_watchers_follow_settings(tmp_path, monkeypatch):
    cfg, state = make(tmp_path, live_channels=["gotaga"])
    cfg.twitch_token_path.write_text("{}")
    started = []

    def fake_watch(channel, cfg, state, opts, twitch, auth, params, stop, status):
        started.append(channel)
        status[channel] = "ok"
        stop.wait(5)

    monkeypatch.setattr("clipbot.watcher.watch_channel", fake_watch)
    monkeypatch.setattr("clipbot.pipeline.run_channels", lambda *a, **k: [])
    pilot = ap.Autopilot(cfg, state, Options())
    pilot._step()
    time.sleep(0.1)
    assert started == ["gotaga"] and pilot.live_status == {"gotaga": "ok"}

    state.save_settings({"live_channels": []})
    pilot._step()
    assert pilot.live_status == {} and not pilot._watchers
    pilot.shutdown()


def test_live_without_twitch_account(tmp_path, monkeypatch):
    cfg, state = make(tmp_path, live_channels=["gotaga"])
    monkeypatch.setattr("clipbot.pipeline.run_channels", lambda *a, **k: [])
    pilot = ap.Autopilot(cfg, state, Options())
    pilot._step()
    assert "connecte ton compte Twitch" in pilot.live_status["gotaga"]
