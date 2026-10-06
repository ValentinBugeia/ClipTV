"""« Ce qui marche sur ton compte » : ce qui distingue tes TikToks qui font le plus de vues.

Compare les vues médianes (moins sensibles à une vidéo virale isolée que la moyenne) par :
durée, jour de publication, ambiance (emoji de la légende), streamer (lien twitch.tv de la
description), question en légende. En tire des conseils simples quand l'écart est net.
"""

from __future__ import annotations

import re
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo

MIN_VIDEOS = 5    # en dessous : pas de conclusions
MIN_GROUP = 2     # vidéos minimum dans un groupe pour en parler
DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
DURATIONS = [(0, 15, "Moins de 15 s"), (15, 25, "15 à 25 s"), (25, 35, "25 à 35 s"),
             (35, 50, "35 à 50 s"), (50, 10_000, "Plus de 50 s")]
MOODS = {"😂": "😂 Humour / fou rire", "😱": "😱 Peur / cri", "😡": "😡 Rage / clash",
         "💀": "💀 Fail", "😭": "😭 Gênant / émotion", "🔥": "🔥 Exploit / clutch",
         "🥰": "🥰 Mignon", "💸": "💸 Argent", "👀": "👀 Intrigue"}


def _duration(seconds: int) -> str | None:
    return next((lb for lo, hi, lb in DURATIONS if lo <= (seconds or 0) < hi), None) \
        if seconds else None


def _mood(text: str) -> str | None:
    first = (text or "").split("\n")[0]
    return next((label for emoji, label in MOODS.items() if emoji in first), None)


def _streamer(text: str) -> str | None:
    m = re.search(r"twitch\.tv/(\w+)", (text or "").lower())
    return m.group(1) if m else None


def _question(text: str) -> str:
    return "Avec une question" if "?" in (text or "") else "Sans question"


def group(videos: list[dict], key) -> list[tuple[str, float, int]]:
    """[(groupe, vues médianes, nb de vidéos)], du meilleur au moins bon."""
    buckets: dict[str, list[int]] = {}
    for v in videos:
        k = key(v)
        if k:
            buckets.setdefault(k, []).append(v["views"])
    return sorted(((k, median(vals), len(vals)) for k, vals in buckets.items()),
                  key=lambda r: -r[1])


def analyse(videos: list[dict], tz: str) -> dict:
    zone = ZoneInfo(tz)
    text = lambda v: f"{v.get('title') or ''}\n{v.get('description') or ''}"  # noqa: E731
    groups = {
        "duration": group(videos, lambda v: _duration(v.get("duration"))),
        "weekday": group(videos, lambda v: DAYS[datetime.fromtimestamp(
            v["create_time"], zone).weekday()] if v.get("create_time") else None),
        "mood": group(videos, lambda v: _mood(v.get("description") or v.get("title"))),
        "streamer": group(videos, lambda v: _streamer(text(v))),
        "question": group(videos, lambda v: _question(v.get("description"))),
        "hour": group(videos, lambda v: datetime.fromtimestamp(
            v["create_time"], zone).strftime("%Hh") if v.get("create_time") else None),
    }
    overall = median([v["views"] for v in videos]) if videos else 0
    return {"count": len(videos), "overall": overall, "groups": groups,
            "tips": tips(groups, overall) if len(videos) >= MIN_VIDEOS else []}


TIP_LABELS = {
    "duration": ("Durée", "privilégie les clips de cette durée",
                 "évite cette durée (coupe plus court)"),
    "weekday": ("Jour", "publie davantage ce jour-là", "publie moins ce jour-là"),
    "hour": ("Heure", "garde un créneau à cette heure-là", "évite ce créneau"),
    "mood": ("Ambiance", "cherche plus de clips de ce type",
             "ce type de moment marche peu chez toi"),
    "streamer": ("Streamer", "publie plus de clips de ce streamer",
                 "ses clips marchent peu chez toi (ClipTV en propose moins)"),
    "question": ("Légende", "garde ce format de légende", "change ce format de légende"),
}


def tips(groups: dict, overall: float) -> list[dict]:
    """Conseils quand un groupe fait nettement mieux (×1,3) ou moins bien (×0,6) que ta
    médiane, avec au moins 2 vidéos. Du plus fort écart au plus faible."""
    out = []
    if overall <= 0:
        return out
    for dim, rows in groups.items():
        good, bad = TIP_LABELS[dim][1], TIP_LABELS[dim][2]
        for name, views, n in rows:
            if n < MIN_GROUP:
                continue
            ratio = views / overall
            if ratio >= 1.3:
                out.append({"dim": TIP_LABELS[dim][0], "name": name, "ratio": ratio, "n": n,
                            "good": True, "advice": good})
            elif ratio <= 0.6:
                out.append({"dim": TIP_LABELS[dim][0], "name": name, "ratio": ratio, "n": n,
                            "good": False, "advice": bad})
    return sorted(out, key=lambda t: -abs(t["ratio"] - 1))[:8]
