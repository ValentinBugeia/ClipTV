"""Choix des meilleurs clips d'une recherche, inspiré de ce qui marche sur les gros comptes
de clips Twitch.

1. **Présélection** (données Twitch, sans rien télécharger) : vues par heure, clip hors
   norme pour son streamer, durée adaptée à TikTok (15-35 s), et résultats de TES anciens
   TikToks pour ce streamer / cette catégorie.
2. **Écoute** des clips présélectionnés (déjà téléchargés pour le montage) :
   - **réaction forte** : un pic de son net (cri, fou rire, rage) par rapport au reste ;
   - **moment fort tôt** : le pic arrive dans les premières secondes, avant que les gens
     ne décrochent.
   Seuls les meilleurs sont montés ; les autres vidéos sont supprimées.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

log = logging.getLogger("clipbot.selection")

SHORTLIST = 3     # clips écoutés pour chaque clip gardé
MAX_SHORTLIST = 12


def shortlist_size(top: int) -> int:
    return min(max(top * SHORTLIST, top), MAX_SHORTLIST)


def duration_factor(seconds: float) -> float:
    """Durée idéale sur TikTok : 15-35 s."""
    if not seconds:
        return 1.0
    if 15 <= seconds <= 35:
        return 1.15
    if seconds < 15:
        return 0.95
    if seconds <= 45:
        return 1.0
    return 0.8


def history_factor(clip, hist: dict) -> float:
    """× vues de tes anciens TikToks du même streamer / de la même catégorie."""
    from statistics import median

    from .potential import MIN_HISTORY, _group_factor

    if len(hist.get("all", [])) < MIN_HISTORY:
        return 1.0
    overall = median(hist["all"])
    factor = 1.0
    ch = _group_factor(hist["channel"].get(clip.broadcaster_name.lower(), []), overall)
    if ch is not None:
        factor *= ch
    category = (getattr(clip, "category", "") or "").lower()
    cat = _group_factor(hist["category"].get(category, []), overall) if category else None
    if cat is not None:
        factor *= cat ** 0.6
    return min(max(factor, 0.25), 4.0)


PREF_DAYS = 60


def preferences(state) -> dict:
    """Ce que tu as gardé ou rejeté ces 60 derniers jours, par streamer et par catégorie :
    publié / programmé = +1, rejeté = -1."""
    import time

    since = int(time.time() - PREF_DAYS * 86400)
    with state.lock:
        rows = state.conn.execute(
            "SELECT channel, category, status FROM clips WHERE updated_at >= ?",
            (since,)).fetchall()
    out: dict = {"channel": {}, "category": {}}
    for channel, category, status in rows:
        delta = {"published": 1, "scheduled": 1, "publishing": 1, "rejected": -1}.get(status)
        if not delta:
            continue
        for kind, key in (("channel", channel), ("category", category)):
            if key:
                out[kind][key.lower()] = out[kind].get(key.lower(), 0) + delta
    return out


def preference_factor(clip, prefs: dict) -> float:
    """Plus de clips des streamers / catégories que tu publies, moins de ceux que tu rejettes."""
    ch = prefs["channel"].get(clip.broadcaster_name.lower(), 0)
    cat = prefs["category"].get((getattr(clip, "category", "") or "").lower(), 0)
    return math.exp(0.12 * min(max(ch, -5), 5) + 0.08 * min(max(cat, -5), 5))


def title_factor(title: str) -> float:
    """Titre qui annonce une réaction (fou rire, rage, cri, clutch…) : petit bonus."""
    import re

    from .captions import MOODS
    from .live import HYPE_TOKENS, LAUGH_RE

    low = (title or "").lower()
    tokens = re.findall(r"[\w+]+", low)
    if any(re.search(p, low) for p, _ in MOODS) or any(
            t in HYPE_TOKENS or LAUGH_RE.match(t) for t in tokens):
        return 1.15
    return 1.0


def chat_factor(state, clip) -> float:
    """Le chat a-t-il explosé au moment du clip ? (seulement si le chat était écouté)"""
    from .live import chat_spike

    try:
        spike = chat_spike(state, clip.broadcaster_name, clip.created_at.timestamp())
    except Exception:
        spike = None
    clip.chat_spike = spike
    if spike is None:
        return 1.0
    return min(max(spike ** 0.35, 0.7), 2.0)


def audio_profile(video: Path) -> dict:
    """{reaction, peak_at, duration} : force du pic de son (× le niveau habituel du clip)
    et seconde où il arrive."""
    import numpy as np

    from .subtitles import SAMPLE_RATE, load_audio

    audio = load_audio(video)
    if audio.size < SAMPLE_RATE:
        return {"reaction": 1.0, "peak_at": 0.0, "duration": audio.size / SAMPLE_RATE}
    win = SAMPLE_RATE // 4
    n = audio.size // win
    rms = np.sqrt(np.mean(np.square(audio[: n * win].reshape(n, win)), axis=1))
    smooth = np.convolve(rms, np.ones(4) / 4, mode="same")  # ~1 s : un vrai moment, pas un clic
    base = max(float(np.median(rms)), 1e-4)
    peak = int(np.argmax(smooth))
    return {"reaction": round(float(smooth[peak]) / base, 2), "peak_at": round(peak * 0.25, 2),
            "duration": round(n * 0.25, 2)}


def audio_factor(profile: dict) -> float:
    """Réaction forte et tôt = clip qui retient. ×0,36 (rien) à ×1,4 (gros pic au début)."""
    reaction = min(max(math.log2(max(profile.get("reaction", 1), 1)) / 3, 0), 1)  # ×8 → 1
    dur = profile.get("duration") or 0
    at = profile.get("peak_at", 0)
    # pic dans les 6 premières secondes (ou le premier tiers) : parfait ; à la fin : mauvais
    pos = at / dur if dur else 0
    early = 1.0 if at <= 6 or pos <= 0.3 else max(0.2, 1 - (pos - 0.3) / 0.7 * 0.8)
    return (0.6 + 0.8 * reaction) * (0.6 + 0.4 * early)


def pick_best(candidates: list, sources: dict, top: int) -> list:
    """Écoute les candidats [(clip, login)] et garde les ``top`` meilleurs.

    ``sources[clip.id]()`` renvoie le chemin de la vidéo téléchargée. Les vidéos écartées
    sont supprimées. Le profil audio est gardé sur le clip (indicateur de potentiel).
    """
    from . import progress

    if len(candidates) <= top:
        return candidates
    progress.step("search", f"Écoute des {len(candidates)} clips présélectionnés "
                            "(réactions fortes, moment fort au début)…")
    scored = []
    for rank, (clip, login) in enumerate(candidates):
        progress.check()
        prior = 1 / (1 + 0.15 * rank)  # ordre de la présélection (données Twitch)
        path = None
        try:
            path = sources[clip.id]()
            clip.audio = audio_profile(Path(path))
            factor = audio_factor(clip.audio)
        except progress.Cancelled:
            raise
        except Exception:
            log.warning("Écoute impossible pour %s : gardé sur ses données Twitch", clip.id)
            clip.audio, factor = None, 0.8
        scored.append((prior * factor, clip, login, path))
        if clip.audio:
            log.info("  %s · réaction ×%.1f à %.0f s → %.2f", clip.title, clip.audio["reaction"],
                     clip.audio["peak_at"], prior * factor)
    scored.sort(key=lambda s: s[0], reverse=True)
    for _, clip, _, path in scored[top:]:  # vidéos non retenues : place libérée
        if path:
            Path(path).unlink(missing_ok=True)
    kept = [(clip, login) for _, clip, login, _ in scored[:top]]
    log.info("Retenus après écoute : %s", ", ".join(c.title for c, _ in kept))
    return kept
