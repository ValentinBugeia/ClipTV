"""Découverte automatique des temps forts : aucune liste de chaînes à fournir.

À chaque passage :
1. on prend les lives les plus regardés dans la langue choisie (API Helix /streams) ;
2. on y ajoute les streamers repérés lors des derniers jours (ceux qui ont fini leur
   live ont encore des clips frais) et les chaînes favorites éventuelles ;
3. on récupère leurs clips récents et on classe **tout le monde ensemble** par
   vues/heure : ce sont les moments que les viewers ont jugés assez forts pour les
   clipper et les partager ;
4. on garde les meilleurs, au plus ``per_channel`` par streamer pour varier le contenu.
"""

from __future__ import annotations

import logging
import time

from .twitch import Clip, TwitchClient, get_top_streams, rank_clips

log = logging.getLogger("clipbot.discover")

MEMORY_DAYS = 3        # durée pendant laquelle un streamer repéré reste scanné
MEMORY_KEY = "discovered"


def candidate_channels(twitch: TwitchClient, state, *, language: str | None,
                       streamers: int, favorites: list[str] = ()) -> dict[str, str]:
    """{login: broadcaster_id} des chaînes à scanner."""
    now = time.time()
    memory: dict = state.get_settings().get(MEMORY_KEY, {})
    for stream in get_top_streams(twitch, language=language, first=streamers):
        memory[stream["user_login"].lower()] = {"id": stream["user_id"], "seen": now}
    memory = {login: v for login, v in memory.items()
              if now - v["seen"] < MEMORY_DAYS * 86400}
    # garde les plus récemment vus si la mémoire grossit trop
    keep = sorted(memory.items(), key=lambda kv: kv[1]["seen"], reverse=True)[:streamers * 3]
    memory = dict(keep)
    state.save_settings({MEMORY_KEY: memory})
    channels = {login: v["id"] for login, v in memory.items()}
    for login in favorites:
        if login not in channels:
            try:
                channels[login] = twitch.get_broadcaster_id(login)
            except Exception:
                log.warning("Chaîne favorite introuvable : %s", login)
    return channels


def standout_score(clips: list[Clip]):
    """Score d'un clip : vues par heure × à quel point il dépasse les clips habituels de
    son streamer. Un petit streamer dont un clip explose passe devant un gros streamer
    dont le clip fait un score moyen pour lui."""
    from statistics import median

    by_channel: dict[str, list[int]] = {}
    for c in clips:
        by_channel.setdefault(c.broadcaster_name.lower(), []).append(c.view_count)
    typical = {k: median(v) for k, v in by_channel.items() if len(v) >= 3}

    def score(clip: Clip) -> float:
        base = typical.get(clip.broadcaster_name.lower())
        ratio = (clip.view_count / max(base, 1)) ** 0.5 if base else 1.0
        return clip.virality() * min(max(ratio, 0.5), 4.0)
    return score


def pick_clips(clips: list[Clip], *, top: int, per_channel: int = 1, min_views: int = 0,
               max_duration: float = 60, language: str | None = None,
               is_done=lambda cid: False) -> list[Clip]:
    """Meilleurs clips tous streamers confondus, en limitant le nombre par streamer."""
    if language:
        clips = [c for c in clips if not c.language or c.language.startswith(language)]
    picked, per = [], {}
    for clip in sorted(rank_clips(clips, min_views=min_views, max_duration=max_duration),
                       key=standout_score(clips), reverse=True):
        key = clip.broadcaster_name.lower()
        if is_done(clip.id) or per.get(key, 0) >= per_channel:
            continue
        picked.append(clip)
        per[key] = per.get(key, 0) + 1
        if len(picked) >= top:
            break
    return picked


def discover(twitch: TwitchClient, state, *, language: str | None = "fr", streamers: int = 30,
             hours: float = 24, top: int = 3, min_views: int = 50, max_duration: float = 60,
             favorites: list[str] = (), per_channel: int = 1) -> list[tuple[Clip, str]]:
    """Retourne [(clip, login)] des meilleurs temps forts du moment."""
    channels = candidate_channels(twitch, state, language=language, streamers=streamers,
                                  favorites=favorites)
    log.info("Découverte : %d chaînes scannées (%s)", len(channels), language or "toutes langues")
    from concurrent.futures import ThreadPoolExecutor

    def fetch(item):
        login, broadcaster_id = item
        try:
            return login, twitch.get_clips(broadcaster_id, since_hours=hours, limit=50)
        except Exception:
            log.warning("Clips indisponibles pour %s", login)
            return login, []

    clips, owner = [], {}
    # 8 requêtes Twitch à la fois (bien sous la limite de 800/min) au lieu d'une par une
    with ThreadPoolExecutor(max_workers=8) as pool:
        for login, found in pool.map(fetch, channels.items()):
            for c in found:
                owner[c.id] = login
            clips += found
    picked = pick_clips(clips, top=top, per_channel=per_channel, min_views=min_views,
                        max_duration=max_duration, language=language, is_done=state.is_done)
    log.info("%d clips trouvés, %d retenus", len(clips), len(picked))
    return [(c, owner[c.id]) for c in picked]


def run_discovery(cfg, state, opts, twitch: TwitchClient, **kwargs) -> list[tuple[str, bool]]:
    from . import progress
    from .pipeline import Prefetcher, process_clip

    results = []
    progress.step("search", f"Lives les plus regardés ({kwargs.get('language') or 'toutes langues'})")
    found = discover(twitch, state, max_duration=opts.max_duration, **kwargs)
    if not found:
        progress.step("search", "Aucun nouveau clip assez viral pour le moment")
    twitch.annotate_categories([clip for clip, _ in found])
    prefetch = Prefetcher(cfg, [clip for clip, _ in found])  # téléchargements anticipés
    try:
        for i, (clip, login) in enumerate(found, 1):
            progress.clip(i, len(found), f"{login} · {clip.title}")
            log.info("→ %s · %s (%d vues, %.0f vues/h) %s", login, clip.title,
                     clip.view_count, clip.virality(), clip.url)
            try:
                ok = process_clip(clip, login, cfg, state, opts, source=prefetch.source(clip))
            except Exception:
                log.exception("Erreur sur %s", clip.id)
                ok = False
            results.append((clip.id, ok))
    finally:
        prefetch.close()
    return results
