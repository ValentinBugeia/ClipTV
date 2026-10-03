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


def test_tiktok_scopes_match_mode():
    import urllib.parse

    from clipbot.tiktok import authorize_url

    def scope(**kw):
        q = urllib.parse.urlparse(authorize_url("k", "https://ex.com/cb", **kw)).query
        return urllib.parse.parse_qs(q)["scope"][0]

    assert scope() == "user.info.basic,video.upload"
    assert scope(direct=True).endswith(",video.publish")


def test_categories():
    from clipbot.twitch import TwitchClient, is_non_gaming

    assert is_non_gaming("IRL") and is_non_gaming("Just Chatting")
    assert not is_non_gaming("League of Legends") and not is_non_gaming("")

    class Fake(TwitchClient):
        calls = 0

        def _get(self, path, params):
            Fake.calls += 1
            return {"data": [{"id": "509658", "name": "Just Chatting"}]}

    tw = Fake("id", "secret")
    clips = [clip("a", 10, 1), clip("b", 10, 1)]
    clips[0].game_id = clips[1].game_id = "509658"
    tw.annotate_categories(clips)
    tw.annotate_categories(clips)
    assert [c.category for c in clips] == ["Just Chatting"] * 2 and Fake.calls == 1  # cache
