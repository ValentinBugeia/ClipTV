"""Publication de Reels Instagram via l'API Instagram Graph (upload « resumable »).

Prérequis : un compte Instagram **professionnel** (créateur ou entreprise) et une app
Meta avec le produit « Instagram » (permissions ``instagram_business_basic`` +
``instagram_business_content_publish``). On récupère un token longue durée (60 jours)
dans le tableau de bord Meta, puis ``clipbot instagram-auth --token …`` ; il est
ensuite rafraîchi automatiquement.

Étapes : création du conteneur REELS → envoi du fichier sur rupload.facebook.com →
attente du traitement → ``media_publish``.

Docs : https://developers.facebook.com/docs/instagram-platform/content-publishing
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

GRAPH_VERSION = "v23.0"
REFRESH_AFTER = 7 * 24 * 3600  # le token vit 60 jours, on le prolonge chaque semaine


def reels_caption(caption: str) -> str:
    """Instagram limite à 2200 caractères et 30 hashtags."""
    count = 0

    def keep(m: re.Match) -> str:
        nonlocal count
        count += 1
        return m.group(0) if count <= 30 else ""

    return re.sub(r"#\w+", keep, caption, flags=re.UNICODE)[:2200].strip()


class InstagramClient:
    def __init__(self, token_path: Path, *, user_id: str | None = None,
                 access_token: str | None = None, host: str = "graph.instagram.com",
                 session: requests.Session | None = None):
        self.token_path = token_path
        self.env_user_id = user_id
        self.env_token = access_token
        self.host = host
        self.session = session or requests.Session()

    @property
    def base(self) -> str:
        return f"https://{self.host}/{GRAPH_VERSION}"

    # ---------- token ----------
    def _load(self) -> dict:
        if self.token_path.exists():
            return json.loads(self.token_path.read_text())
        if self.env_token:
            return {"access_token": self.env_token, "obtained_at": int(time.time()),
                    "user_id": self.env_user_id}
        raise SystemExit("Pas de token Instagram : lance `clipbot instagram-auth --token …`.")

    def save(self, access_token: str, user_id: str | None = None) -> dict:
        tok = {"access_token": access_token, "obtained_at": int(time.time()),
               "user_id": user_id or self.env_user_id}
        if not tok["user_id"]:
            me = self._get("/me", {"fields": "user_id,username"}, token=access_token)
            tok["user_id"], tok["username"] = me.get("user_id") or me.get("id"), \
                me.get("username")
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(tok, indent=2))
        return tok

    def _token(self) -> dict:
        tok = self._load()
        stale = time.time() > tok.get("obtained_at", 0) + REFRESH_AFTER
        if stale and self.host == "graph.instagram.com":
            resp = self.session.get(f"https://{self.host}/refresh_access_token", params={
                "grant_type": "ig_refresh_token", "access_token": tok["access_token"]},
                timeout=15)
            if resp.ok and "access_token" in resp.json():
                tok = self.save(resp.json()["access_token"], tok.get("user_id"))
        if not tok.get("user_id"):
            raise SystemExit("INSTAGRAM_USER_ID manquant (id du compte Instagram pro).")
        return tok

    # ---------- API ----------
    def _get(self, path: str, params: dict | None = None, token: str | None = None) -> dict:
        token = token or self._token()["access_token"]
        resp = self.session.get(f"{self.base}{path}",
                                params={**(params or {}), "access_token": token}, timeout=30)
        payload = resp.json()
        if resp.status_code >= 400 or "error" in payload:
            raise RuntimeError(f"Erreur Instagram {path} : {payload.get('error', payload)}")
        return payload

    def _post(self, path: str, params: dict) -> dict:
        resp = self.session.post(f"{self.base}{path}",
                                 params={**params, "access_token": self._token()["access_token"]},
                                 timeout=30)
        payload = resp.json()
        if resp.status_code >= 400 or "error" in payload:
            raise RuntimeError(f"Erreur Instagram {path} : {payload.get('error', payload)}")
        return payload

    def account(self) -> dict:
        tok = self._token()
        return self._get(f"/{tok['user_id']}", {"fields": "username"})

    def publish_reel(self, video: Path, *, caption: str, timeout: float = 600,
                     interval: float = 10) -> str:
        tok = self._token()
        user_id, token = tok["user_id"], tok["access_token"]
        container = self._post(f"/{user_id}/media", {
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": reels_caption(caption),
            "share_to_feed": "true",
        })
        size = video.stat().st_size
        with video.open("rb") as fh:
            resp = self.session.post(
                container["uri"], data=fh,
                headers={"Authorization": f"OAuth {token}", "offset": "0",
                         "file_size": str(size)},
                timeout=600)
        if resp.status_code >= 400:
            raise RuntimeError(f"Erreur Instagram (upload) : {resp.text}")

        deadline = time.time() + timeout
        while True:
            status = self._get(f"/{container['id']}", {"fields": "status_code,status"})
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram a refusé la vidéo : {status.get('status')}")
            if time.time() > deadline:
                raise TimeoutError("Traitement Instagram trop long")
            time.sleep(interval)
        return self._post(f"/{user_id}/media_publish", {"creation_id": container["id"]})["id"]
