"""Récupération des clips Twitch via l'API Helix et classement par viralité."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


@dataclass
class Clip:
    id: str
    url: str
    title: str
    broadcaster_name: str
    creator_name: str
    view_count: int
    created_at: datetime
    duration: float
    language: str = ""
    game_id: str = ""

    @classmethod
    def from_api(cls, data: dict) -> "Clip":
        return cls(
            id=data["id"],
            url=data["url"],
            title=data.get("title", ""),
            broadcaster_name=data.get("broadcaster_name", ""),
            creator_name=data.get("creator_name", ""),
            view_count=int(data.get("view_count", 0)),
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
            duration=float(data.get("duration", 0)),
            language=data.get("language", ""),
            game_id=data.get("game_id", ""),
        )

    def virality(self, now: datetime | None = None) -> float:
        """Vues par heure depuis la création du clip (avec un plancher d'1h).

        Un clip récent qui accumule vite des vues est mieux classé qu'un vieux
        clip avec un total un peu plus élevé.
        """
        now = now or datetime.now(timezone.utc)
        age_hours = max((now - self.created_at).total_seconds() / 3600, 1.0)
        return self.view_count / age_hours


def rank_clips(
    clips: list[Clip],
    *,
    min_views: int = 0,
    min_duration: float = 0,
    max_duration: float = 180,
    now: datetime | None = None,
) -> list[Clip]:
    eligible = [
        c
        for c in clips
        if c.view_count >= min_views and min_duration <= c.duration <= max_duration
    ]
    return sorted(eligible, key=lambda c: c.virality(now), reverse=True)


class TwitchClient:
    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self._token: str | None = None
        self._token_expiry = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        resp = self.session.post(
            TOKEN_URL,
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + payload.get("expires_in", 3600)
        return self._token

    def _get(self, path: str, params: dict) -> dict:
        resp = self.session.get(
            f"{HELIX}{path}",
            params=params,
            headers={"Client-Id": self.client_id, "Authorization": f"Bearer {self._get_token()}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_broadcaster_id(self, login: str) -> str:
        data = self._get("/users", {"login": login.lower()})["data"]
        if not data:
            raise ValueError(f"Chaîne Twitch introuvable : {login}")
        return data[0]["id"]

    def get_clips(self, broadcaster_id: str, *, since_hours: float = 24, limit: int = 100) -> list[Clip]:
        now = datetime.now(timezone.utc)
        params = {
            "broadcaster_id": broadcaster_id,
            "started_at": (now - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ended_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "first": min(limit, 100),
        }
        clips: list[Clip] = []
        while len(clips) < limit:
            payload = self._get("/clips", params)
            clips.extend(Clip.from_api(d) for d in payload.get("data", []))
            cursor = payload.get("pagination", {}).get("cursor")
            if not cursor:
                break
            params["after"] = cursor
        return clips[:limit]
