"""Statistiques : vidéos TikTok (vues, j'aime…) reliées aux clips de cliptv.

Les statistiques TikTok demandent les scopes ``user.info.stats`` et ``video.list``
(produit « Display API » de l'app TikTok), activés depuis la page Comptes. Elles sont
rafraîchies toutes les heures par le pilote automatique et à la demande.

Chaque vidéo TikTok est reliée au clip d'origine (streamer, catégorie) :
1. via le suivi de publication TikTok (``publicaly_available_post_id``) ;
2. à défaut, en comparant le début de la légende.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from statistics import mean
from zoneinfo import ZoneInfo

from .config import Config
from .state import State

log = logging.getLogger("clipbot.stats")

ENABLED = "tiktok_stats"          # réglage : statistiques activées
ACCOUNT = "tiktok_account"        # dernières stats du compte
UPDATED = "stats_updated_at"
ERROR = "stats_error"
LINKS = "tiktok_links"            # publish_id -> video_id déjà résolus
REFRESH_EVERY = 3600


def _norm(text: str) -> str:
    """Début de légende comparable (sans hashtags, ponctuation ni casse)."""
    text = re.sub(r"#\w+", " ", text or "", flags=re.UNICODE)
    return re.sub(r"\W+", "", text.lower(), flags=re.UNICODE)[:40]


def _client(cfg: Config):
    from .tiktok import TikTokClient

    cfg.require("tiktok_client_key", "tiktok_client_secret")
    return TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret, cfg.tiktok_token_path)


def link_videos(state: State, videos: list[dict], client=None) -> dict[str, str]:
    """{video_id: clip_id} pour les vidéos TikTok qui viennent de cliptv."""
    links: dict = dict(state.get_settings().get(LINKS, {}))
    by_publish = {}
    with state.lock:
        rows = state.conn.execute(
            "SELECT clip_id, post_id FROM posts WHERE platform='tiktok' AND status='ok'"
        ).fetchall()
    for clip_id, publish_id in rows:
        by_publish[publish_id] = clip_id
        if publish_id not in links and client is not None:
            try:  # l'ID de la vidéo n'est connu qu'une fois publiée depuis la boîte TikTok
                ids = client.status(publish_id).get("publicaly_available_post_id") or []
                if ids:
                    links[publish_id] = str(ids[0])
            except Exception:
                pass
    state.save_settings({LINKS: links})
    result = {vid: by_publish[pid] for pid, vid in links.items() if pid in by_publish}

    # repli : même début de légende (publication manuelle, ou lien pas encore connu)
    captions = {}
    for clip in state.list("published"):
        key = _norm(clip.get("caption") or "")
        if len(key) >= 12:
            captions[key] = clip["clip_id"]
    for v in videos:
        vid = str(v["id"])
        if vid in result:
            continue
        key = _norm(v.get("video_description") or v.get("title") or "")
        for cap, clip_id in captions.items():
            if key and (key.startswith(cap[:24]) or cap.startswith(key[:24])):
                result[vid] = clip_id
                break
    return result


def refresh(cfg: Config, state: State) -> str:
    """Récupère les stats TikTok et les enregistre. Retourne un message d'état."""
    try:
        client = _client(cfg)
        account = client.account_stats()
        videos = client.list_videos()
        links = link_videos(state, videos, client)
    except (Exception, SystemExit) as exc:
        from .errors import explain

        raw = str(exc)
        if re.search(r"scope|permission", raw, re.IGNORECASE):
            msg = ("TikTok refuse l'accès aux statistiques → ajoute le produit Display API "
                   "(scopes user.info.stats et video.list) à ton app sur "
                   "developers.tiktok.com, clique sur « Activer les statistiques », puis "
                   "page Comptes → Reconnecter TikTok.")
        else:
            msg = f"Statistiques TikTok indisponibles : {explain(exc)}"
        state.save_settings({ERROR: msg, UPDATED: int(time.time())})
        log.warning("Statistiques TikTok indisponibles : %s", msg)
        return msg
    state.save_videos([
        {"video_id": str(v["id"]), "title": v.get("title") or "",
         "description": v.get("video_description") or "",
         "create_time": int(v.get("create_time") or 0), "cover": v.get("cover_image_url"),
         "share_url": v.get("share_url"), "views": int(v.get("view_count") or 0),
         "likes": int(v.get("like_count") or 0), "comments": int(v.get("comment_count") or 0),
         "shares": int(v.get("share_count") or 0), "duration": int(v.get("duration") or 0),
         "clip_id": links.get(str(v["id"]))}
        for v in videos])
    state.save_settings({ACCOUNT: account, ERROR: None, UPDATED: int(time.time())})
    return f"{len(videos)} vidéo(s) TikTok mises à jour"


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", (text or "").lower(), flags=re.UNICODE) if len(w) > 3}


def on_tiktok(state: State):
    """Fonction clip -> True si ce clip est déjà sur le compte TikTok (publié depuis ce PC,
    un autre PC ou à la main). Se base sur la liste des vidéos du compte (statistiques)."""
    with state.lock:
        rows = state.conn.execute(
            "SELECT clip_id, title, description FROM tiktok_videos").fetchall()
    linked = {r[0] for r in rows if r[0]}
    texts = [f"{r[1] or ''} {r[2] or ''}" for r in rows]
    norms = [re.sub(r"\W+", "", t.lower(), flags=re.UNICODE) for t in texts]
    words = [_words(t) for t in texts]

    def check(clip) -> bool:
        if clip.id in linked:
            return True
        title = re.sub(r"\W+", "", (clip.title or "").lower(), flags=re.UNICODE)
        if len(title) >= 12 and any(title[:30] in n for n in norms):
            return True
        # légende réécrite (Claude) : même streamer + la plupart des mots du titre
        tw = _words(clip.title)
        channel = clip.broadcaster_name.lower().replace(" ", "")
        return len(tw) >= 3 and any(
            channel in n and len(tw & w) >= 0.7 * len(tw) for n, w in zip(norms, words))
    return check


def refresh_before_search(cfg: Config, state: State, max_age: float = 900) -> None:
    """Avant une recherche : liste des vidéos du compte à jour (moins de 15 min), pour ne
    pas reproposer un clip déjà publié. Silencieux si les statistiques ne sont pas actives."""
    s = state.get_settings()
    if not s.get(ENABLED) or not cfg.tiktok_token_path.exists():
        return
    if time.time() - (s.get(UPDATED) or 0) < max_age:
        return
    try:
        refresh(cfg, state)
    except Exception:
        log.warning("Liste des vidéos TikTok non rafraîchie", exc_info=True)


def due(state: State) -> bool:
    s = state.get_settings()
    return bool(s.get(ENABLED)) and time.time() - (s.get(UPDATED) or 0) >= REFRESH_EVERY


def engagement(v: dict) -> float:
    """(j'aime + commentaires + partages) / vues."""
    return (v["likes"] + v["comments"] + v["shares"]) / v["views"] if v["views"] else 0.0


def summary(state: State, *, since: float, tz: str) -> dict:
    """Agrégats pour la page Statistiques sur la période (vidéos publiées depuis ``since``)."""
    videos = state.videos(since)
    clips = {c["clip_id"]: c for c in state.list()}
    for v in videos:
        clip = clips.get(v["clip_id"] or "")
        v["channel"] = clip["channel"] if clip else None
        v["category"] = (clip or {}).get("category") or None
        v["engagement"] = engagement(v)

    def group(key) -> list[tuple[str, float, int]]:
        buckets: dict[str, list[int]] = {}
        for v in videos:
            k = key(v)
            if k:
                buckets.setdefault(k, []).append(v["views"])
        rows = [(k, mean(vals), len(vals)) for k, vals in buckets.items()]
        return sorted(rows, key=lambda r: -r[1])

    zone = ZoneInfo(tz)
    totals = {k: sum(v[k] for v in videos) for k in ("views", "likes", "comments", "shares")}
    totals["videos"] = len(videos)
    totals["engagement"] = ((totals["likes"] + totals["comments"] + totals["shares"])
                            / totals["views"] if totals["views"] else 0.0)
    with state.lock:
        activity = dict(state.conn.execute(
            "SELECT status, COUNT(*) FROM clips WHERE updated_at >= ? GROUP BY status",
            (int(since),)).fetchall())
    settings = state.get_settings()
    return {
        "enabled": bool(settings.get(ENABLED)),
        "account": settings.get(ACCOUNT) or {},
        "updated_at": settings.get(UPDATED),
        "error": settings.get(ERROR),
        "totals": totals,
        "videos": videos,
        "by_channel": group(lambda v: v["channel"])[:8],
        "by_category": group(lambda v: v["category"])[:8],
        "by_hour": sorted(group(lambda v: datetime.fromtimestamp(
            v["create_time"], zone).strftime("%Hh") if v["create_time"] else None)),
        "activity": activity,
    }
