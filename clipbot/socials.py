"""Compte TikTok des streamers, pour les mentionner (@) dans la description.

Trouvé sur la chaîne Twitch : réseaux sociaux de la page « À propos », panneaux et bio.
Gardé en mémoire (réglage ``tiktok_handles``) ; tu peux corriger ou ajouter un compte dans
Pilote auto → Comptes TikTok des streamers (« - » = ne jamais mentionner ce streamer).
"""

from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("clipbot.socials")

KEY = "tiktok_handles"
GQL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # client public du site twitch.tv
FOUND_TTL = 14 * 86400      # compte trouvé : revérifié toutes les 2 semaines
MISSING_TTL = 3 * 86400     # rien trouvé : nouvel essai dans 3 jours
HANDLE_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]{2,24})", re.I)
TEXT_RE = re.compile(r"tik ?tok\W{0,6}@([A-Za-z0-9_.]{2,24})", re.I)

QUERIES = [  # requêtes séparées : si l'une n'est plus acceptée par Twitch, les autres passent
    "query($l:String!){user(login:$l){channel{socialMedias{name url}}}}",
    "query($l:String!){user(login:$l){panels{...on DefaultPanel{linkURL description}}}}",
    "query($l:String!){user(login:$l){description}}",
]


def clean(handle: str) -> str:
    return (handle or "").strip().lstrip("@").rstrip(".").lower()


def find_in_text(*texts: str) -> str | None:
    for text in texts:
        m = HANDLE_RE.search(text or "") or TEXT_RE.search(text or "")
        if m:
            return clean(m.group(1))
    return None


def lookup(login: str, timeout: float = 8) -> str | None:
    """Compte TikTok affiché sur la chaîne Twitch, ou None."""
    import requests

    body = [{"query": q, "variables": {"l": login.lower()}} for q in QUERIES]
    resp = requests.post(GQL, json=body, headers={"Client-ID": WEB_CLIENT_ID}, timeout=timeout)
    resp.raise_for_status()
    texts: list[str] = []
    for item in resp.json():
        user = ((item or {}).get("data") or {}).get("user") or {}
        for social in ((user.get("channel") or {}).get("socialMedias") or []):
            texts.insert(0, social.get("url") or "")  # le lien officiel d'abord
        for panel in user.get("panels") or []:
            texts += [panel.get("linkURL") or "", panel.get("description") or ""]
        texts.append(user.get("description") or "")
    return find_in_text(*texts)


def handles(state) -> dict:
    return state.get_settings().get(KEY) or {}


def tiktok_handle(state, login: str) -> str | None:
    """@ TikTok du streamer (sans le @), d'après tes corrections puis la chaîne Twitch."""
    login = (login or "").lower()
    known = handles(state)
    entry = known.get(login)
    if entry and (entry.get("manual") or time.time() - entry.get("at", 0) <
                  (FOUND_TTL if entry.get("handle") else MISSING_TTL)):
        return entry.get("handle") or None
    try:
        handle = lookup(login)
    except Exception as exc:
        log.info("Compte TikTok de %s introuvable pour l'instant (%s)", login, exc)
        return (entry or {}).get("handle") or None
    if handle:
        log.info("Compte TikTok de %s : @%s", login, handle)
    known = handles(state)  # relu : une autre recherche a pu écrire entre-temps
    known[login] = {"handle": handle, "at": int(time.time())}
    state.save_settings({KEY: known})
    return handle


def parse_lines(text: str) -> dict[str, str | None]:
    """« streamer @compte » (ou « streamer = compte », « streamer - ») par ligne."""
    out: dict[str, str | None] = {}
    for line in (text or "").splitlines():
        parts = [p for p in re.split(r"[\s=:,;→>]+", line.strip()) if p]
        if len(parts) >= 2 and re.fullmatch(r"\w{2,25}", parts[0]):
            out[parts[0].lower()] = None if parts[1] == "-" else clean(parts[1]) or None
    return out


def save_manual(state, text: str) -> int:
    """Enregistre la liste corrigée : les lignes deviennent des choix manuels, les comptes
    trouvés automatiquement qui ont disparu de la liste sont oubliés."""
    now = int(time.time())
    manual = parse_lines(text)
    known = {k: v for k, v in handles(state).items() if k in manual}
    for login, handle in manual.items():
        old = known.get(login)
        if old is None or old.get("handle") != handle or old.get("manual"):
            known[login] = {"handle": handle, "at": now, "manual": True}
    state.save_settings({KEY: known})
    return len(manual)


def as_lines(state) -> str:
    rows = sorted(handles(state).items())
    return "\n".join(f"{login} @{v['handle']}" if v.get("handle") else f"{login} -"
                     for login, v in rows if v.get("handle") or v.get("manual"))
