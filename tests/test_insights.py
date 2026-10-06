"""« Ce qui marche sur ton compte »."""

from datetime import datetime
from zoneinfo import ZoneInfo

from clipbot import insights


def video(views, dur, desc, day=6, hour=18):
    ts = datetime(2026, 10, day, hour, 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
    return {"views": views, "duration": dur, "description": desc, "title": "",
            "create_time": int(ts)}


def test_analyse_and_tips():
    videos = [video(5000, 20, "Il hurle 😱\nT'aurais eu peur ? 👇\n🎮 twitch.tv/nico_la", 5),
              video(4800, 22, "Cri 😱\nQui aurait crié ? 😭\n🎮 twitch.tv/nico_la", 5),
              video(600, 55, "Partie calme 🔥\n🎮 twitch.tv/autre", 7),
              video(500, 58, "Ranked 🔥\n🎮 twitch.tv/autre", 7),
              video(1500, 30, "Moment 😂\n🎮 twitch.tv/zz", 6)]
    data = insights.analyse(videos, "Europe/Paris")
    assert data["overall"] == 1500
    assert data["groups"]["duration"][0][0] == "15 à 25 s"
    assert data["groups"]["streamer"][0][0] == "nico_la"
    good = [t for t in data["tips"] if t["good"]]
    bad = [t for t in data["tips"] if not t["good"]]
    assert any(t["name"] == "15 à 25 s" for t in good)
    assert any(t["name"] == "Plus de 50 s" for t in bad)
    assert any(t["name"] == "Avec une question" for t in good)


def test_not_enough_videos():
    data = insights.analyse([video(100, 20, "x")], "Europe/Paris")
    assert data["tips"] == [] and data["count"] == 1
