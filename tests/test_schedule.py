from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from clipbot import pipeline
from clipbot.config import Config
from clipbot.pipeline import Options, publish_clip
from clipbot.schedule import format_when, next_slot, publish_due, schedule_clip
from clipbot.state import State

PARIS = ZoneInfo("Europe/Paris")
SLOTS = ["18:00", "12:30", "21:00"]


def at(*args):
    return datetime(*args, tzinfo=PARIS)


def test_next_slot_same_day_and_rollover():
    assert next_slot(at(2026, 10, 3, 10, 0), SLOTS, []) == at(2026, 10, 3, 12, 30)
    assert next_slot(at(2026, 10, 3, 12, 30), SLOTS, []) == at(2026, 10, 3, 18, 0)
    assert next_slot(at(2026, 10, 3, 22, 0), SLOTS, []) == at(2026, 10, 4, 12, 30)


def test_next_slot_skips_taken():
    taken = [int(at(2026, 10, 3, 12, 30).timestamp()), int(at(2026, 10, 3, 18, 0).timestamp())]
    assert next_slot(at(2026, 10, 3, 10, 0), SLOTS, taken) == at(2026, 10, 3, 21, 0)


def test_next_slot_handles_dst_change():
    # passage à l'heure d'hiver le 25/10/2026 : 18:00 reste 18:00 heure locale
    slot = next_slot(at(2026, 10, 25, 13, 0), ["18:00"], [])
    assert slot.hour == 18 and slot.utcoffset().total_seconds() == 3600


def test_invalid_slot():
    with pytest.raises(SystemExit):
        next_slot(at(2026, 10, 3, 10, 0), ["18h"], [])


def test_format_when():
    assert format_when(int(at(2026, 10, 3, 18, 0).timestamp()), "Europe/Paris") == \
        "sam 03/10 à 18:00"


@pytest.fixture()
def env(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    cfg.platforms = ["tiktok", "youtube"]
    cfg.post_slots = SLOTS
    cfg.timezone = "Europe/Paris"
    state = State(cfg.db_path)
    state.save_settings({"auto_publish": True})  # app validée : ClipTV publie
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    for cid in ("a", "b"):
        state.record(cid, "kamet0", "rendered", title=cid, output_path=str(video),
                     caption="légende")
    return cfg, state


def test_schedule_clips_take_distinct_slots(env):
    cfg, state = env
    now = at(2026, 10, 3, 10, 0)
    assert schedule_clip(state, cfg, "a", "nouvelle", now=now) == at(2026, 10, 3, 12, 30)
    assert schedule_clip(state, cfg, "b", now=now) == at(2026, 10, 3, 18, 0)
    assert state.get("a")["caption"] == "nouvelle"
    assert [c["clip_id"] for c in state.list("scheduled")] == ["a", "b"]
    assert state.unschedule("b") and state.get("b")["status"] == "rendered"


def test_publish_due_partial_failure_then_retry(env, monkeypatch):
    cfg, state = env
    calls = []

    def fake_publish(platform, path, caption, cfg, opts):
        calls.append(platform)
        if platform == "youtube" and calls.count("youtube") == 1:
            raise RuntimeError("quota dépassé")
        return f"{platform}-id"

    monkeypatch.setattr(pipeline, "publish_to", fake_publish)
    schedule_clip(state, cfg, "a", now=at(2026, 10, 3, 10, 0))
    assert publish_due(state, cfg, Options(), now=at(2026, 10, 3, 12, 0).timestamp()) == 0
    assert publish_due(state, cfg, Options(), now=at(2026, 10, 3, 12, 31).timestamp()) == 1
    row = state.get("a")
    assert row["status"] == "failed" and "quota" in row["error"]
    assert row["publish_id"] == "tiktok-id"
    assert state.posts("a")["tiktok"]["status"] == "ok"

    # nouvelle tentative : seul YouTube est relancé
    assert state.claim("a")
    assert publish_clip("a", cfg, state, Options()) == []
    assert calls == ["tiktok", "youtube", "youtube"]
    assert state.get("a")["status"] == "published"
    assert not state.claim("a")  # déjà publié


def test_claim_is_exclusive(env):
    _, state = env
    assert state.claim("a") and not state.claim("a")
    assert state.get("a")["status"] == "publishing"
