"""Programmation des publications sur des créneaux horaires fixes.

Les clips validés sont placés sur le prochain créneau libre (ex. 12:30, 18:00, 21:00
heure de Paris) au lieu de partir tous d'un coup : TikTok et YouTube favorisent un
rythme régulier, et les créneaux visent les heures où l'audience est la plus active.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger("clipbot.schedule")


def parse_slots(slots: list[str]) -> list[dtime]:
    parsed = []
    for s in slots:
        try:
            h, m = s.split(":")
            parsed.append(dtime(int(h), int(m)))
        except ValueError:
            raise SystemExit(f"Créneau invalide dans CLIPBOT_POST_SLOTS : {s!r} (format HH:MM)")
    if not parsed:
        raise SystemExit("CLIPBOT_POST_SLOTS est vide")
    return sorted(set(parsed))


def next_slot(now: datetime, slots: list[str], taken: list[int] | set[int],
              tz: str = "Europe/Paris", max_days: int = 60) -> datetime:
    """Prochain créneau libre strictement après ``now`` (datetime avec fuseau)."""
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    taken = {int(t) for t in taken}
    times = parse_slots(slots)
    for day in range(max_days):
        date = local_now.date() + timedelta(days=day)
        for t in times:
            candidate = datetime.combine(date, t, tzinfo=zone)
            if candidate > local_now and int(candidate.timestamp()) not in taken:
                return candidate
    raise RuntimeError(f"Aucun créneau libre dans les {max_days} prochains jours")


def schedule_clip(state, cfg, clip_id: str, caption: str | None = None,
                  now: datetime | None = None) -> datetime | None:
    """Programme un clip sur le prochain créneau libre. Retourne l'heure, ou None."""
    from datetime import timezone

    with state.lock:  # deux validations simultanées ne prennent pas le même créneau
        when = next_slot(now or datetime.now(timezone.utc), cfg.post_slots,
                         state.scheduled_times(), cfg.timezone)
        if not state.schedule(clip_id, int(when.timestamp()), caption):
            return None
    return when


def format_when(ts: int | None, tz: str) -> str:
    if not ts:
        return ""
    jours = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    d = datetime.fromtimestamp(ts, ZoneInfo(tz))
    return f"{jours[d.weekday()]} {d:%d/%m à %H:%M}"


def publish_due(state, cfg, opts, now: float | None = None) -> int:
    """Publie les clips dont le créneau est passé. Retourne le nombre traité."""
    from .pipeline import publish_clip

    state.recover_stuck()
    done = 0
    for clip in state.due(now or time.time()):
        if not state.claim(clip["clip_id"]):
            continue  # déjà pris par un autre publieur
        log.info("⏰ Créneau atteint : publication de %s", clip["clip_id"])
        publish_clip(clip["clip_id"], cfg, state, opts)
        done += 1
    return done


def run_publisher(state, cfg, opts, interval: float = 60,
                  stop: threading.Event | None = None) -> None:
    """Boucle du planificateur : vérifie les créneaux toutes les ``interval`` secondes."""
    stop = stop or threading.Event()
    log.info("Planificateur actif : créneaux %s (%s), plateformes %s",
             ", ".join(cfg.post_slots), cfg.timezone, ", ".join(cfg.platforms))
    while not stop.is_set():
        try:
            publish_due(state, cfg, opts)
        except Exception:  # le planificateur ne doit jamais s'arrêter
            log.exception("Erreur du planificateur")
        stop.wait(interval)
