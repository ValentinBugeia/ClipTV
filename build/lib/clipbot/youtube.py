"""Publication de YouTube Shorts via l'API YouTube Data v3.

Connexion : Device Flow Google (client OAuth de type « TV et appareils à entrée
limitée »), on valide un code sur google.com/device — marche aussi sur un serveur.
Une vidéo verticale de moins de 3 min est automatiquement classée en Short.

Docs : https://developers.google.com/youtube/v3/guides/uploading_a_video
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests

DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
# seul scope YouTube autorisé en Device Flow ; il inclut l'upload
SCOPE = "https://www.googleapis.com/auth/youtube"
GAMING_CATEGORY = "20"

_HASHTAG = re.compile(r"#\w+", re.UNICODE)


def shorts_metadata(caption: str) -> tuple[str, str, list[str]]:
    """Découpe une légende TikTok en (titre, description, tags) YouTube."""
    lines = [ln.strip() for ln in caption.splitlines() if ln.strip()]
    hashtags = _HASHTAG.findall(caption)
    first = next((ln for ln in lines if _HASHTAG.sub("", ln).strip()), "Clip Twitch")
    title = re.sub(r"\s+", " ", _HASHTAG.sub("", first)).strip()
    title = title.replace("<", "").replace(">", "")  # interdits par YouTube
    if "#shorts" not in (h.lower() for h in hashtags):
        hashtags.append("#Shorts")
    if len(title) > 90:
        title = title[:89].rstrip() + "…"
    title = f"{title} #Shorts"[:100]
    description = caption.replace("<", "").replace(">", "")
    if "#shorts" not in description.lower():
        description += "\n#Shorts"
    tags = [h.lstrip("#") for h in hashtags][:15]
    return title, description[:5000], tags


class YouTubeClient:
    def __init__(self, client_id: str, client_secret: str, token_path: Path,
                 session: requests.Session | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_path = token_path
        self.session = session or requests.Session()

    # ---------- OAuth ----------
    def _save(self, payload: dict, refresh_token: str | None = None) -> dict:
        payload["obtained_at"] = int(time.time())
        payload.setdefault("refresh_token", refresh_token)  # Google ne le renvoie qu'une fois
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(payload, indent=2))
        return payload

    def start_device_flow(self) -> dict:
        resp = self.session.post(DEVICE_URL, data={"client_id": self.client_id, "scope": SCOPE},
                                 timeout=15)
        resp.raise_for_status()
        return resp.json()  # device_code, user_code, verification_url, interval, expires_in

    def poll_device_flow(self, device: dict) -> dict:
        deadline = time.time() + device.get("expires_in", 1800)
        interval = device.get("interval", 5)
        while time.time() < deadline:
            time.sleep(interval)
            resp = self.session.post(TOKEN_URL, data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "device_code": device["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }, timeout=15)
            payload = resp.json()
            if resp.status_code == 200:
                return self._save(payload)
            err = payload.get("error")
            if err == "slow_down":
                interval += 5
            elif err != "authorization_pending":
                raise RuntimeError(f"Autorisation YouTube refusée : {payload}")
        raise TimeoutError("Code YouTube expiré, relance `clipbot youtube-auth`.")

    def access_token(self) -> str:
        if self.token_path.exists():
            tok = json.loads(self.token_path.read_text())
            if time.time() < tok["obtained_at"] + tok.get("expires_in", 0) - 300:
                return tok["access_token"]
            refresh = tok.get("refresh_token")
        else:
            refresh = os.environ.get("YOUTUBE_REFRESH_TOKEN")
        if not refresh:
            raise SystemExit("Pas de token YouTube : lance d'abord `clipbot youtube-auth`.")
        resp = self.session.post(TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        }, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"Refresh du token YouTube refusé : {resp.text}")
        return self._save(resp.json(), refresh)["access_token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token()}"}

    # ---------- API ----------
    def channel(self) -> dict:
        resp = self.session.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                                headers=self._headers(), timeout=15)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return items[0]["snippet"] if items else {}

    def upload(self, video: Path, *, caption: str, privacy: str = "private") -> str:
        title, description, tags = shorts_metadata(caption)
        body = {
            "snippet": {"title": title, "description": description, "tags": tags,
                        "categoryId": GAMING_CATEGORY},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        }
        size = video.stat().st_size
        resp = self.session.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=body,
            headers={**self._headers(), "X-Upload-Content-Type": "video/mp4",
                     "X-Upload-Content-Length": str(size)},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Erreur YouTube (init) : {resp.text}")
        location = resp.headers["Location"]
        with video.open("rb") as fh:
            resp = self.session.put(location, data=fh,
                                    headers={"Content-Type": "video/mp4",
                                             "Content-Length": str(size)},
                                    timeout=600)
        if resp.status_code >= 400:
            raise RuntimeError(f"Erreur YouTube (upload) : {resp.text}")
        return resp.json()["id"]
