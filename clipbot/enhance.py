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
