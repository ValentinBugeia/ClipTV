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
    category: str = ""  # nom de la catégorie Twitch (rempli par annotate_categories)
    broadcaster_id: str = ""

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
            broadcaster_id=data.get("broadcaster_id", ""),
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


# catégories sans jeu : un visage y est filmé dans la scène, jamais une facecam incrustée
NON_GAMING = {
    "just chatting", "irl", "travel & outdoors", "talk shows & podcasts", "music", "art",
    "food & drink", "sports", "asmr", "special events", "pools, hot tubs, and beaches",
    "makers & crafting", "fitness & health", "science & technology", "beauty & body art",
    "animals, aquariums, and zoos", "politics", "dj", "dance",
}


def is_non_gaming(category: str) -> bool:
    return category.strip().lower() in NON_GAMING


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

    def game_names(self, game_ids) -> dict[str, str]:
        """{game_id: nom de la catégorie}, avec cache."""
        cache = self.__dict__.setdefault("_games", {})
        missing = [g for g in {*game_ids} - set(cache) if g]
        for i in range(0, len(missing), 100):
            for g in self._get("/games", {"id": missing[i:i + 100]}).get("data", []):
                cache[g["id"]] = g.get("name", "")
        return {g: cache.get(g, "") for g in game_ids if g}

    def annotate_categories(self, clips) -> None:
        """Renseigne ``clip.category`` (sans bloquer le traitement en cas d'erreur)."""
        try:
            names = self.game_names([c.game_id for c in clips])
        except Exception:
            return
        for c in clips:
            c.category = names.get(c.game_id, "")

    def get_broadcaster_id(self, login: str) -> str:
        data = self._get("/users", {"login": login.lower()})["data"]
        if not data:
            raise ValueError(f"Chaîne Twitch introuvable : {login}")
        return data[0]["id"]

    def ids_for(self, logins) -> dict[str, str]:
        """{login: id} des chaînes (par paquets de 100) ; les chaînes inconnues sont ignorées."""
        names = [n.lower() for n in dict.fromkeys(logins) if n]
        out: dict[str, str] = {}
        for i in range(0, len(names), 100):
            data = self._get("/users", [("login", x) for x in names[i:i + 100]])["data"]
            out.update({u["login"]: u["id"] for u in data})
        return out

    def logins(self, broadcaster_ids) -> dict[str, str]:
        """{id: login} des chaînes (par paquets de 100)."""
        ids = [i for i in dict.fromkeys(broadcaster_ids) if i]
        out: dict[str, str] = {}
        for i in range(0, len(ids), 100):
            data = self._get("/users", [("id", x) for x in ids[i:i + 100]])["data"]
            out.update({u["id"]: u["login"] for u in data})
        return out

    def get_game_clips(self, game_id: str, *, since_hours: float = 24, limit: int = 100) -> list[Clip]:
        """Clips les plus vus d'une catégorie, toutes chaînes confondues (même hors ligne)."""
        return self.get_clips("", game_id=game_id, since_hours=since_hours, limit=limit)

    def get_clips(self, broadcaster_id: str, *, since_hours: float = 24, limit: int = 100,
                  game_id: str = "") -> list[Clip]:
        now = datetime.now(timezone.utc)
        params = {
            **({"game_id": game_id} if game_id else {"broadcaster_id": broadcaster_id}),
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


# ---------------------------------------------------------------------------
# Token utilisateur (nécessaire pour créer des clips pendant un live)
# ---------------------------------------------------------------------------

DEVICE_URL = "https://id.twitch.tv/oauth2/device"
USER_SCOPES = "clips:edit"


class TwitchUserAuth:
    """Device Code Flow : l'utilisateur valide un code sur twitch.tv/activate.

    Le token est stocké dans ``token_path`` et rafraîchi automatiquement.
    """

    def __init__(self, client_id: str, client_secret: str | None, token_path,
                 session: requests.Session | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_path = token_path
        self.session = session or requests.Session()

    def _save(self, payload: dict) -> dict:
        import json

        payload["obtained_at"] = int(time.time())
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(payload, indent=2))
        return payload

    def start_device_flow(self) -> dict:
        resp = self.session.post(
            DEVICE_URL, data={"client_id": self.client_id, "scopes": USER_SCOPES}, timeout=15
        )
        resp.raise_for_status()
        return resp.json()  # device_code, user_code, verification_uri, interval, expires_in

    def poll_device_flow(self, device: dict) -> dict:
        deadline = time.time() + device.get("expires_in", 1800)
        while time.time() < deadline:
            time.sleep(device.get("interval", 5))
            resp = self.session.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "scopes": USER_SCOPES,
                    "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return self._save(resp.json())
            if "authorization_pending" not in resp.text:
                raise RuntimeError(f"Autorisation Twitch refusée : {resp.text}")
        raise TimeoutError("Code Twitch expiré, relance `clipbot twitch-auth`.")

    def access_token(self) -> str:
        import json

        if not self.token_path.exists():
            raise SystemExit("Pas de token Twitch utilisateur : lance `clipbot twitch-auth`.")
        tok = json.loads(self.token_path.read_text())
        if time.time() > tok["obtained_at"] + tok.get("expires_in", 0) - 300:
            data = {"client_id": self.client_id, "grant_type": "refresh_token",
                    "refresh_token": tok["refresh_token"]}
            if self.client_secret:
                data["client_secret"] = self.client_secret
            resp = self.session.post(TOKEN_URL, data=data, timeout=15)
            resp.raise_for_status()
            tok = self._save(resp.json())
        return tok["access_token"]


def _user_headers(client: TwitchClient, auth: TwitchUserAuth) -> dict:
    return {"Client-Id": client.client_id, "Authorization": f"Bearer {auth.access_token()}"}


def get_stream(client: TwitchClient, login: str) -> dict | None:
    """Infos du live en cours, ou None si la chaîne est hors ligne."""
    data = client._get("/streams", {"user_login": login.lower()})["data"]
    return data[0] if data else None


def get_top_streams(client: TwitchClient, *, language: str | None = None,
                    first: int = 50) -> list[dict]:
    """Lives en cours les plus regardés (triés par spectateurs), filtrés par langue."""
    params = {"first": min(max(first, 1), 100), "type": "live"}
    if language:
        params["language"] = language
    return client._get("/streams", params)["data"]


def get_clip(client: TwitchClient, clip_id: str) -> Clip | None:
    data = client._get("/clips", {"id": clip_id})["data"]
    return Clip.from_api(data[0]) if data else None


def create_clip(client: TwitchClient, auth: TwitchUserAuth, broadcaster_id: str,
                *, wait: float = 45.0) -> Clip | None:
    """Crée un clip des dernières secondes du live et attend qu'il soit disponible."""
    resp = client.session.post(
        f"{HELIX}/clips",
        params={"broadcaster_id": broadcaster_id},
        headers=_user_headers(client, auth),
        timeout=15,
    )
    resp.raise_for_status()
    clip_id = resp.json()["data"][0]["id"]
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(5)
        clip = get_clip(client, clip_id)
        if clip:
            return clip
    return None
