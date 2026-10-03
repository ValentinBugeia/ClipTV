from datetime import datetime, timedelta, timezone

from clipbot.twitch import Clip, rank_clips
from clipbot.tiktok import chunk_plan

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def clip(cid, views, hours_ago, duration=30):
    return Clip(cid, f"https://clips.twitch.tv/{cid}", cid, "chan", "x", views,
                NOW - timedelta(hours=hours_ago), duration)


def test_rank_prefers_fast_growing_clips():
    clips = [clip("old", 2000, 20), clip("fresh", 600, 1), clip("tiny", 10, 1)]
    ranked = rank_clips(clips, min_views=50, now=NOW)
    assert [c.id for c in ranked] == ["fresh", "old"]


def test_rank_filters_duration():
    assert rank_clips([clip("long", 1000, 1, duration=200)], now=NOW) == []


def test_from_api():
    c = Clip.from_api({"id": "Abc", "url": "u", "title": "t", "view_count": 5,
                       "created_at": "2026-01-01T10:00:00Z", "duration": 27.5})
    assert c.created_at.tzinfo is not None and c.duration == 27.5


def test_chunk_plan():
    assert chunk_plan(5_000_000) == (5_000_000, 1)
    size = 100 * 1024 * 1024 + 123
    chunk, total = chunk_plan(size)
    assert chunk == 10 * 1024 * 1024 and total == 10
