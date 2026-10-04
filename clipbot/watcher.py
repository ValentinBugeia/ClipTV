"""Surveillance d'un live Twitch : attend le live, lit le chat, clippe chaque pic.

Utilisé par ``clipbot watch`` et par le pilote automatique. ``stop`` permet d'arrêter
proprement la surveillance (changement de réglages, arrêt du serveur).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("clipbot.watch")


@dataclass
class WatchParams:
    ratio: float = 3.0       # activité du chat vs normale pour déclencher
    min_rate: float = 1.5    # score minimal par seconde
    cooldown: float = 90.0   # secondes minimum entre deux clips
    forever: bool = True     # après la fin du live, attend le suivant


def watch_channel(channel: str, cfg, state, opts, twitch, auth, params: WatchParams,
                  stop: threading.Event | None = None, status: dict | None = None) -> None:
    """Boucle de surveillance d'une chaîne. ``status[channel]`` reflète l'état courant."""
    stop = stop or threading.Event()
    status = status if status is not None else {}
    broadcaster_id = None
    while not stop.is_set():
        try:
            broadcaster_id = broadcaster_id or twitch.get_broadcaster_id(channel)
            if not _wait_live(twitch, channel, stop, status):
                return
            status[channel] = "🔴 en live, chat surveillé"
            _watch_live(channel, cfg, state, opts, twitch, auth, broadcaster_id, params, stop,
                        status)
        except Exception as exc:  # panne API Twitch : on reprend
            if not params.forever:
                raise
            log.exception("Erreur pendant la surveillance de %s, reprise dans 30 s", channel)
            status[channel] = f"⚠️ erreur ({exc}), reprise dans 30 s"
            stop.wait(30)
            continue
        if not params.forever:
            return


def _wait_live(twitch, channel: str, stop: threading.Event, status: dict) -> bool:
    from .twitch import get_stream

    while not stop.is_set():
        try:
            if get_stream(twitch, channel):
                return True
        except Exception:
            log.exception("Statut du live indisponible")
        status[channel] = "hors ligne, vérification toutes les 2 min"
        log.debug("%s est hors ligne, nouvelle vérification dans 2 min…", channel)
        stop.wait(120)
    return False


def _watch_live(channel, cfg, state, opts, twitch, auth, broadcaster_id, params: WatchParams,
                stop: threading.Event, status: dict) -> None:
    from .live import SpikeDetector, message_weight, read_chat
    from .pipeline import process_clip
    from .twitch import create_clip, get_stream

    detector = SpikeDetector(ratio=params.ratio, min_score=params.min_rate,
                             cooldown=params.cooldown)
    last_live_check = time.time()
    clips = 0
    log.info("Surveillance du chat de %s (seuil x%.1f)…", channel, params.ratio)
    chat = read_chat(channel)
    try:
        for event in chat:
            if stop.is_set():
                return
            now = time.time()
            if event:
                detector.add(event[0], message_weight(event[2]))
            if now - last_live_check > 300:
                last_live_check = now
                try:
                    live = get_stream(twitch, channel)
                except Exception:
                    log.exception("Statut du live indisponible")
                    live = True
                if not live:
                    log.info("Fin du live de %s.", channel)
                    return
            intensity = detector.check(now)
            if intensity is None:
                continue
            recent, baseline = detector.rates(now)
            log.info("🔥 Pic de chat sur %s (%.1f/s vs %.1f/s, x%.1f) → création d'un clip",
                     channel, recent, baseline, intensity)
            try:
                clip = create_clip(twitch, auth, broadcaster_id)
            except Exception:
                log.exception("Création du clip impossible")
                continue
            if not clip:
                log.warning("Clip pas encore disponible, ignoré")
                continue
            log.info("Clip créé : %s", clip.url)
            twitch.annotate_categories([clip])
            status[channel] = "🔴 en live · traitement d'un clip…"
            # traité dans la foulée (le chat continue d'être lu ensuite)
            from . import progress

            progress.begin(f"Clip du live de {channel}")
            ok = process_clip(clip, channel, cfg, state, opts)
            progress.end("Clip du live prêt" if ok else "Clip du live en erreur")
            if ok:
                clips += 1
            status[channel] = f"🔴 en live, chat surveillé · {clips} clip(s) ce live"
    finally:
        chat.close()
