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
SCOPES = "user.info.basic,video.upload,video.publish"

MAX_SINGLE_CHUNK = 64 * 1024 * 1024
CHUNK_SIZE = 10 * 1024 * 1024


def authorize_url(client_key: str, redirect_uri: str, state: str | None = None) -> str:
    params = {
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state or secrets.token_urlsafe(16),
    }
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

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        resp = self.session.post(
            f"{API}/oauth/token/",
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
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

    def creator_info(self) -> dict:
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
