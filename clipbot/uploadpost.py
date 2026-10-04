"""Publication TikTok via Upload-Post (upload-post.com), un service déjà validé par TikTok.

Tant que l'app TikTok de l'utilisateur n'est pas validée par TikTok, l'API officielle ne
livre les vidéos qu'aux comptes privés. Upload-Post possède une app validée : on lui
envoie le clip et il le publie en public sur le compte TikTok connecté chez lui.

Réglages (Comptes → Clés API) : ``UPLOADPOST_API_KEY`` (clé API Upload-Post) et
``UPLOADPOST_USER`` (nom du profil créé sur upload-post.com, auquel TikTok est relié).
API : https://github.com/Upload-Post/upload-post-pip
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

log = logging.getLogger("clipbot.uploadpost")

BASE_URL = "https://api.upload-post.com/api"


class UploadPostError(RuntimeError):
    pass


class UploadPostClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Apikey {api_key}"})

    @classmethod
    def from_env(cls) -> "UploadPostClient":
        key = os.environ.get("UPLOADPOST_API_KEY")
        if not key:
            raise SystemExit("Configuration manquante : UPLOADPOST_API_KEY")
        return cls(key, os.environ.get("UPLOADPOST_BASE_URL", BASE_URL))

    def _check(self, resp: requests.Response) -> dict:
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400 or data.get("success") is False:
            msg = (data.get("message") or data.get("error") or data.get("detail")
                   or resp.text[:300] or f"HTTP {resp.status_code}")
            raise UploadPostError(f"Upload-Post ({resp.status_code}) : {msg}")
        return data

    def users(self) -> list[dict]:
        """Profils du compte Upload-Post, avec leurs réseaux connectés."""
        data = self._check(self.session.get(f"{self.base_url}/uploadposts/users", timeout=30))
        return data.get("profiles") or data.get("users") or []

    def tiktok_account(self, user: str) -> str:
        """Vérifie que le profil ``user`` existe et a un TikTok relié ; retourne un libellé."""
        profiles = self.users()
        names = [str(p.get("username") or p.get("name") or "") for p in profiles]
        profile = next((p for p, n in zip(profiles, names) if n == user), None)
        if profile is None:
            raise UploadPostError(f"profil « {user} » introuvable sur Upload-Post "
                                  f"(profils : {', '.join(n for n in names if n) or 'aucun'})")
        tiktok = _find_tiktok(profile)
        if not tiktok:
            raise UploadPostError(f"aucun compte TikTok relié au profil « {user} »")
        if isinstance(tiktok, dict):
            return str(tiktok.get("display_name") or tiktok.get("username") or "TikTok")
        return str(tiktok) if isinstance(tiktok, str) else "TikTok"

    def upload_tiktok(self, video: Path, *, caption: str, user: str,
                      privacy_level: str = "PUBLIC_TO_EVERYONE") -> str:
        """Publie la vidéo sur TikTok. Retourne un identifiant de suivi."""
        data = [("user", user), ("title", caption[:2200]), ("platform[]", "tiktok"),
                ("privacy_level", privacy_level), ("post_mode", "DIRECT_POST"),
                ("async_upload", "false")]  # réponse = résultat final de la publication
        with video.open("rb") as fh:
            resp = self.session.post(f"{self.base_url}/upload", data=data,
                                     files=[("video", (video.name, fh, "video/mp4"))],
                                     timeout=900)
        result = self._check(resp)
        tiktok = (result.get("results") or {}).get("tiktok") or {}
        if isinstance(tiktok, dict) and tiktok.get("success") is False:
            raise UploadPostError(f"Upload-Post : TikTok a refusé la vidéo : "
                                  f"{tiktok.get('error') or tiktok.get('message') or tiktok}")
        ident = (tiktok.get("publish_id") or tiktok.get("url") or result.get("request_id")
                 or result.get("job_id") or "upload-post") if isinstance(tiktok, dict) \
            else (result.get("request_id") or "upload-post")
        log.info("Upload-Post : vidéo envoyée sur TikTok (%s)", ident)
        return str(ident)


def _find_tiktok(obj):
    """Cherche l'entrée « tiktok » dans la description d'un profil (format souple)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() == "tiktok" and value:
                return value
        for value in obj.values():
            found = _find_tiktok(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_tiktok(value)
            if found:
                return found
    return None
