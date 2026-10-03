"""Publication via l'API officielle TikTok Content Posting.

Deux modes :
- ``draft``  : la vidéo arrive dans la boîte de réception TikTok (notification),
  tu finalises la publication depuis l'app. Scope ``video.upload``. Fonctionne
  sans audit de l'app.
- ``direct`` : publication directe. Scope ``video.publish``. Tant que l'app TikTok
  n'est pas auditée, les vidéos sont forcément publiées en privé (SELF_ONLY).

Docs : https://developers.tiktok.com/doc/content-posting-api-get-started
"""

from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path

import requests

API = "https://open.tiktokapis.com/v2"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
# draft (boîte de réception) : video.upload suffit ; direct : video.publish en plus.
# Ne demander que ce que l'app TikTok possède, sinon TikTok refuse la connexion.
SCOPES = "user.info.basic,video.upload"
SCOPES_DIRECT = SCOPES + ",video.publish"
# statistiques (produit « Display API ») : demandées seulement si activées dans l'app
SCOPES_STATS = "user.info.stats,video.list"
VIDEO_FIELDS = ("id,title,video_description,create_time,cover_image_url,share_url,"
                "view_count,like_count,comment_count,share_count,duration")

MAX_SINGLE_CHUNK = 64 * 1024 * 1024
CHUNK_SIZE = 10 * 1024 * 1024


PKCE_SETTING = "tiktok_pkce"  # code_verifier en attente (base locale)


def new_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge) pour la connexion TikTok.

    Particularité TikTok : le challenge est le SHA-256 du verifier encodé en
    **hexadécimal** (et non en base64url comme dans la RFC 7636).
    """
    import hashlib
    import string

    alphabet = string.ascii_letters + string.digits + "-._~"
    verifier = "".join(secrets.choice(alphabet) for _ in range(64))
    return verifier, hashlib.sha256(verifier.encode()).hexdigest()


def authorize_url(client_key: str, redirect_uri: str, state: str | None = None,
                  direct: bool = False, code_challenge: str | None = None,
                  stats: bool = False) -> str:
    scope = SCOPES_DIRECT if direct else SCOPES
    if stats:
        scope += "," + SCOPES_STATS
    params = {
        "client_key": client_key,
        "scope": scope,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state or secrets.token_urlsafe(16),
    }
    if code_challenge:
        params.update(code_challenge=code_challenge, code_challenge_method="S256")
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def chunk_plan(size: int) -> tuple[int, int]:
    """Retourne (chunk_size, total_chunk_count) selon les règles TikTok.

    Fichier < 64 Mo : un seul chunk. Sinon chunks de 10 Mo, le dernier absorbe le reste.
    """
    if size <= MAX_SINGLE_CHUNK:
        return size, 1
    return CHUNK_SIZE, size // CHUNK_SIZE


class TikTokClient:
    def __init__(self, client_key: str, client_secret: str, token_path: Path,
                 session: requests.Session | None = None):
        self.client_key = client_key
        self.client_secret = client_secret
        self.token_path = token_path
        self.session = session or requests.Session()

    # ---------- OAuth ----------
    def _save_token(self, payload: dict) -> dict:
        payload["obtained_at"] = int(time.time())
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(payload, indent=2))
        return payload

    def exchange_code(self, code: str, redirect_uri: str,
                      code_verifier: str | None = None) -> dict:
        data = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        resp = self.session.post(
            f"{API}/oauth/token/",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "access_token" not in payload:
            raise RuntimeError(f"Échange OAuth TikTok refusé : {payload}")
        return self._save_token(payload)

    def _refresh(self, refresh_token: str) -> dict:
        resp = self.session.post(
            f"{API}/oauth/token/",
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "access_token" not in payload:
            raise RuntimeError(f"Refresh du token TikTok refusé : {payload}")
        return self._save_token(payload)

    def access_token(self) -> str:
        if not self.token_path.exists():
            # utile en CI : un refresh token fourni en secret suffit à démarrer
            refresh = os.environ.get("TIKTOK_REFRESH_TOKEN")
            if not refresh:
                raise SystemExit("Pas de token TikTok : lance d'abord `clipbot tiktok-auth`.")
            return self._refresh(refresh)["access_token"]
        tok = json.loads(self.token_path.read_text())
        if time.time() > tok["obtained_at"] + tok.get("expires_in", 0) - 300:
            tok = self._refresh(tok["refresh_token"])
        return tok["access_token"]

    # ---------- API ----------
    def _post(self, path: str, body: dict) -> dict:
        resp = self.session.post(
            f"{API}{path}",
            json=body,
            headers={
                "Authorization": f"Bearer {self.access_token()}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=30,
        )
        payload = resp.json()
        err = payload.get("error", {})
        if resp.status_code >= 400 or err.get("code") not in (None, "ok"):
            raise RuntimeError(f"Erreur TikTok {path} : {err or payload}")
        return payload.get("data", {})

    def user_info(self) -> dict:
        """Nom du compte connecté (scope user.info.basic, valable en mode brouillon)."""
        resp = self.session.get(
            f"{API}/user/info/", params={"fields": "open_id,display_name"},
            headers={"Authorization": f"Bearer {self.access_token()}"}, timeout=15)
        payload = resp.json()
        err = payload.get("error", {})
        if resp.status_code >= 400 or err.get("code") not in (None, "ok"):
            raise RuntimeError(f"Erreur TikTok /user/info : {err or payload}")
        return payload.get("data", {}).get("user", {})

    def _get_api(self, path: str, params: dict) -> dict:
        resp = self.session.get(f"{API}{path}", params=params, timeout=30,
                                headers={"Authorization": f"Bearer {self.access_token()}"})
        payload = resp.json()
        err = payload.get("error", {})
        if resp.status_code >= 400 or err.get("code") not in (None, "ok"):
            raise RuntimeError(f"Erreur TikTok {path} : {err or payload}")
        return payload.get("data", {})

    def account_stats(self) -> dict:
        """Abonnés, j'aime, nombre de vidéos (scope user.info.stats)."""
        return self._get_api("/user/info/", {"fields": "display_name,avatar_url,"
                             "follower_count,following_count,likes_count,video_count"}
                             ).get("user", {})

    def list_videos(self, limit: int = 200) -> list[dict]:
        """Vidéos publiées du compte, avec leurs statistiques (scope video.list)."""
        videos, cursor = [], None
        while len(videos) < limit:
            body = {"max_count": 20, **({"cursor": cursor} if cursor else {})}
            resp = self.session.post(
                f"{API}/video/list/", params={"fields": VIDEO_FIELDS}, json=body,
                headers={"Authorization": f"Bearer {self.access_token()}",
                         "Content-Type": "application/json; charset=UTF-8"},
                timeout=30)
            payload = resp.json()
            err = payload.get("error", {})
            if resp.status_code >= 400 or err.get("code") not in (None, "ok"):
                raise RuntimeError(f"Erreur TikTok /video/list : {err or payload}")
            data = payload.get("data", {})
            videos += data.get("videos", [])
            cursor = data.get("cursor")
            if not data.get("has_more") or not cursor:
                break
        return videos[:limit]

    def creator_info(self) -> dict:
        """Infos de publication directe (nécessite le scope video.publish)."""
        return self._post("/post/publish/creator_info/query/", {})

    def _upload(self, upload_url: str, video: Path, chunk_size: int, total: int) -> None:
        size = video.stat().st_size
        with video.open("rb") as fh:
            for i in range(total):
                start = i * chunk_size
                end = size - 1 if i == total - 1 else start + chunk_size - 1
                fh.seek(start)
                data = fh.read(end - start + 1)
                resp = self.session.put(
                    upload_url,
                    data=data,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {start}-{end}/{size}",
                    },
                    timeout=300,
                )
                resp.raise_for_status()

    def publish(self, video: Path, *, caption: str, mode: str = "draft",
                privacy_level: str = "SELF_ONLY") -> str:
        size = video.stat().st_size
        chunk_size, total = chunk_plan(size)
        source = {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk_size,
            "total_chunk_count": total,
        }
        if mode == "draft":
            data = self._post("/post/publish/inbox/video/init/", {"source_info": source})
        elif mode == "direct":
            body = {
                "post_info": {
                    "title": caption[:2200],
                    "privacy_level": privacy_level,
                    "disable_comment": False,
                    "disable_duet": False,
                    "disable_stitch": False,
                },
                "source_info": source,
            }
            data = self._post("/post/publish/video/init/", body)
        else:
            raise ValueError(f"Mode inconnu : {mode}")
        self._upload(data["upload_url"], video, chunk_size, total)
        return data["publish_id"]

    def status(self, publish_id: str) -> dict:
        return self._post("/post/publish/status/fetch/", {"publish_id": publish_id})

    def wait(self, publish_id: str, timeout: float = 300, interval: float = 5) -> dict:
        deadline = time.time() + timeout
        while True:
            st = self.status(publish_id)
            if st.get("status") in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"):
                return st
            if time.time() > deadline:
                return st
            time.sleep(interval)
