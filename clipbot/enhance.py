"""Améliorations du montage pour la rétention TikTok.

- ``hook_text`` : titre d'accroche affiché en gros pendant les premières secondes ;
- ``find_start`` : coupe le début « mou » (silence, attente) pour démarrer sur l'action ;
- ``has_burned_subtitles`` : repère les sous-titres déjà incrustés dans le stream, pour ne
  pas en ajouter une deuxième couche.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("clipbot.enhance")

HOOK_MAX = 42          # caractères : 2 lignes lisibles sur téléphone
MAX_TRIM = 4.0         # secondes coupées au maximum au début
MIN_KEEP = 8.0         # durée minimale gardée


def hook_text(title: str) -> str:
    """Titre de clip Twitch → accroche courte en majuscules (sans emoji : la police ne
    les affiche pas). Vide si le titre n'apporte rien."""
    text = "".join(ch for ch in title or "" if ord(ch) <= 0xFFFF
                   and unicodedata.category(ch) not in ("So", "Cs", "Co"))
    text = re.sub(r"https?://\S+|[#@]\w+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–—|:.,")
    if len(re.sub(r"\W", "", text)) < 4:
        return ""
    if len(text) > HOOK_MAX:
        cut = text[:HOOK_MAX].rsplit(" ", 1)[0]
        text = (cut if len(cut) >= 12 else text[:HOOK_MAX]).rstrip(" ,.;:") + "…"
    return text.upper()


def find_start(audio, sample_rate: int, words: list | None = None, duration: float = 0) -> float:
    """Début conseillé (s) : juste avant le premier son fort ou la première parole.

    Prudent : 0 si le clip démarre déjà vite, jamais plus de ``MAX_TRIM`` secondes coupées,
    et au moins ``MIN_KEEP`` secondes gardées.
    """
    import numpy as np

    if audio is None or len(audio) < sample_rate:
        return 0.0
    win = sample_rate // 4  # fenêtres de 0,25 s
    n = len(audio) // win
    rms = np.sqrt(np.mean(np.square(audio[: n * win].reshape(n, win)), axis=1))
    loud_ref = np.percentile(rms, 90)
    if loud_ref <= 1e-4:  # clip silencieux
        return 0.0
    loud = np.nonzero(rms >= 0.35 * loud_ref)[0]
    t_loud = loud[0] * 0.25 if len(loud) else 0.0
    candidates = [t_loud]
    if words:
        candidates.append(float(words[0].start))
    start = max(min(candidates) - 0.3, 0.0)
    total = duration or len(audio) / sample_rate
    start = min(start, MAX_TRIM, max(total - MIN_KEEP, 0.0))
    return round(start, 2) if start >= 0.5 else 0.0


def has_burned_subtitles(video: Path, samples: int = 16) -> bool:
    """Sous-titres déjà incrustés : une ligne de texte clair, centrée dans le bas de l'image,
    présente sur une bonne partie du clip ET qui change (une interface de jeu ne change pas)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        return False
    lines, masks = 0, []
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((i + 0.5) * total / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        band = cv2.cvtColor(frame[int(h * 0.68):int(h * 0.96), int(w * 0.1):int(w * 0.9)],
                            cv2.COLOR_BGR2GRAY)
        bright = (band >= 215).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(bright, 8)
        # lettres : hautes de 2 à 7 % de l'image, pas plus larges que hautes (ou presque)
        chars = [s for s in stats[1:] if 0.018 * h <= s[3] <= 0.07 * h
                 and s[2] <= 1.5 * s[3] and s[4] >= 12]
        found, xs = False, None
        if len(chars) >= 6:
            ys = np.array([s[1] + s[3] / 2 for s in chars])
            row = np.abs(ys - np.median(ys)) <= 0.025 * h
            xs = np.array([s[0] + s[2] / 2 for s in chars])[row]
            if row.sum() >= 6:
                center = (xs.min() + xs.max()) / 2
                found = abs(center - band.shape[1] / 2) <= 0.15 * band.shape[1]
        if found:
            lines += 1
            masks.append(np.sort(xs))  # positions des lettres de la ligne
    cap.release()
    if lines < max(4, samples * 0.35):
        return False
    def same(a, b) -> bool:  # même texte = mêmes lettres aux mêmes endroits
        if abs(len(a) - len(b)) > 2:
            return False
        near = sum(bool(np.any(np.abs(b - x) <= 4)) for x in a)
        return near >= 0.8 * max(len(a), len(b))

    # au moins 3 changements de phrase entre deux images prises à la suite
    changing = sum(not same(a, b) for a, b in zip(masks, masks[1:])) >= 3
    if changing:
        log.info("Sous-titres déjà présents dans le stream (%d/%d images)", lines, samples)
    return changing


def speech_energy(words: list) -> dict:
    """Ce qui se dit dans le clip : débit (mots/s) et mots de réaction (mdr, non mais,
    wtf, cris…). Un clip où ça parle vite et fort retient mieux qu'un gameplay silencieux."""
    import re as _re

    from .captions import MOODS
    from .live import HYPE_TOKENS, LAUGH_RE

    if not words:
        return {"talk_rate": 0.0, "hype_words": 0}
    span = max(words[-1].end - words[0].start, 1.0)
    text = " ".join(w.text.lower() for w in words)
    tokens = _re.findall(r"[\w+]+", text)
    hype = sum(1 for t in tokens if t in HYPE_TOKENS or LAUGH_RE.match(t))
    hype += sum(len(_re.findall(p, text)) for p, _ in MOODS)
    hype += len(_re.findall(r"non mais|c'est pas possible|attends|oh non|t'es sérieux", text))
    return {"talk_rate": round(len(words) / span, 2), "hype_words": hype}


TAIL_KEEP = 0.8   # secondes gardées après la dernière parole / le dernier son fort


def _rms(audio, sample_rate: int):
    import numpy as np

    win = sample_rate // 4
    n = len(audio) // win
    return np.sqrt(np.mean(np.square(audio[: n * win].reshape(n, win)), axis=1))


def find_end(audio, sample_rate: int, words: list | None = None, start: float = 0.0) -> float | None:
    """Fin conseillée (s) : juste après la chute (dernière parole ou dernier son fort).
    Une fin sèche donne envie de revoir le clip ; TikTok compte les revisionnages.
    None si la fin est déjà serrée (moins de 2 s à couper)."""
    import numpy as np

    if audio is None or len(audio) < sample_rate * 4:
        return None
    rms = _rms(audio, sample_rate)
    total = len(rms) * 0.25
    ref = np.percentile(rms, 90)
    if ref <= 1e-4:
        return None
    loud = np.nonzero(rms >= 0.35 * ref)[0]
    last = loud[-1] * 0.25 + 0.25 if len(loud) else total
    if words:
        last = max(last, float(words[-1].end))
    end = min(last + TAIL_KEEP, total)
    if total - end < 2.0 or end - start < MIN_KEEP:
        return None
    return round(end, 2)


def peak_time(audio, sample_rate: int) -> tuple[float, float]:
    """(seconde du moment le plus fort, force × le niveau habituel)."""
    import numpy as np

    rms = _rms(audio, sample_rate)
    if not len(rms):
        return 0.0, 1.0
    smooth = np.convolve(rms, np.ones(4) / 4, mode="same")
    i = int(np.argmax(smooth))
    return i * 0.25, float(smooth[i]) / max(float(np.median(rms)), 1e-4)
