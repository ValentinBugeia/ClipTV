"""Choix des meilleurs clips d'une recherche, inspiré de ce qui marche sur les gros comptes
de clips Twitch.

1. **Présélection** (données Twitch, sans rien télécharger) : vues par heure, clip hors
   norme pour son streamer, durée adaptée à TikTok (15-35 s), et résultats de TES anciens
   TikToks pour ce streamer / cette catégorie.
2. **Écoute** des moments présélectionnés (extrait léger de la rediffusion autour de
   chaque clip, voir ``moments``) : transcription en phrases, puis découpe complète
   (situation → chute → réaction) ; réaction forte = un pic de son net (cri, fou rire,
   rage) par rapport au reste.
3. **Radar** (Claude) : choisit lui-même le début et la fin de chaque clip, le note et
   écarte ceux qui ne se comprennent pas sans contexte.
   Seuls les meilleurs sont téléchargés en 1080p et montés ; les extraits sont supprimés.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

log = logging.getLogger("clipbot.selection")

SHORTLIST = 3     # clips écoutés pour chaque clip gardé
MAX_SHORTLIST = 12


def shortlist_size(top: int, radar: bool = False) -> int:
    """Clips présélectionnés (téléchargés et écoutés). Avec le Radar : 2 par clip demandé
    (8 au plus) ; une 2e tournée n'a lieu que s'il manque des clips publiables."""
    if radar:
        return min(max(top * 2, top + 1), 8)
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


def jury_for(opts, language: str | None = None, state=None):
    """Le juré Claude si activé et disponible (Claude Code sur ce PC), sinon None.
    Avec ``state`` : les avis sont gardés 3 jours, un clip déjà jugé ne l'est pas deux
    fois (ni téléchargé, ni réécouté)."""
    from . import llm

    if not getattr(opts, "jury", False) or not llm.available():
        return None
    from . import jury

    def run(items):
        verdicts = jury.judge(items, language=language)
        if state is not None:
            try:
                jury.remember(state, verdicts, [clip for clip, _ in items])
            except Exception:
                log.warning("Avis du Radar non mémorisés", exc_info=True)
        return verdicts
    run.language = language  # transcription rapide faite pendant les téléchargements
    run.cache = jury.remembered(state) if state is not None else {}
    return run


def to_download(clips: list, jury) -> list:
    """Clips à télécharger pour l'écoute : pas ceux que le Radar a déjà jugés."""
    cache = getattr(jury, "cache", None) or {}
    return [c for c in clips if c.id not in cache]


def pick_best(candidates: list, sources: dict, top: int, jury=None, note=None,
              more=None) -> list:
    """Écoute les candidats [(clip, login)] et garde les ``top`` meilleurs.

    ``sources[clip.id]()`` renvoie le chemin de la vidéo téléchargée. Les vidéos écartées
    sont supprimées. Le profil audio est gardé sur le clip (indicateur de potentiel).
    ``jury(items)`` : avis de Claude {clip.id: {score, standalone, reason}} ; les clips
    sous la note minimale (ou pas clairs sans contexte) ne sont pas publiables tels quels.
    ``more()`` : s'il manque des clips publiables, autres candidats à faire juger
    ((candidats, sources), une seule fois). En dernier recours seulement, les moins
    mauvais complètent : on rend toujours ``top`` clips quand il y a assez de candidats.
    ``note(clip)`` : note sur 10 (engagement attendu) ; si donnée, c'est elle qui classe.
    """
    if len(candidates) <= top and jury is None:
        return candidates
    scored, below = _listen(candidates, sources, jury)
    if jury is not None and len(scored) < top and more is not None:
        extra = more()
        if extra and extra[0]:
            from . import progress

            log.info("Radar : %d clip(s) publiable(s) sur %d → 2e tournée sur %d autres clips",
                     len(scored), top, len(extra[0]))
            progress.step("radar", f"Pas assez de clips publiables : {len(extra[0])} autres "
                                   "clips regardés")
            more_scored, more_below = _listen(extra[0], extra[1], jury, offset=len(candidates))
            scored, below = scored + more_scored, below + more_below
    if note is not None:  # classement final : la note sur 10 (engagement attendu)
        def with_note(entry):
            try:
                entry[1].note = note(entry[1])
            except Exception:
                log.warning("Note impossible pour %s", entry[1].id, exc_info=True)
                entry[1].note = None
            return (entry[1].note if entry[1].note is not None else entry[0], *entry[1:])
        scored, below = [with_note(x) for x in scored], [with_note(x) for x in below]
        for value, clip, _, _ in scored + below:
            log.info("  Note %.1f/10 : %s", value, clip.title)
    scored.sort(key=lambda s: s[0], reverse=True)
    if len(scored) < top and below:  # pas assez de bons clips : les moins mauvais complètent
        # les plus cohérents d'abord (avis du Radar), puis la note
        below.sort(key=lambda s: ((s[1].jury or {}).get("standalone", True),
                                  (s[1].jury or {}).get("score", 0), s[0]), reverse=True)
        extra = below[: top - len(scored)]
        log.info("Radar : %d clip(s) sous la note minimale ajouté(s) pour atteindre %d",
                 len(extra), top)
        scored += extra
        below = below[len(extra):]
    for _, clip, _, path in below:
        if path:
            Path(path).unlink(missing_ok=True)
    for _, clip, _, path in scored[top:]:  # vidéos non retenues : place libérée
        if path:
            Path(path).unlink(missing_ok=True)
    kept = [(clip, login) for _, clip, login, _ in scored[:top]]
    log.info("Retenus après écoute : %s", ", ".join(c.title for c, _ in kept))
    return kept


def _listen(candidates: list, sources: dict, jury, offset: int = 0) -> tuple[list, list]:
    """Écoute (son, paroles) puis avis du Radar : (clips retenus, clips en réserve)."""
    from . import progress

    progress.step("search", f"Écoute des {len(candidates)} clips présélectionnés "
                            "(réactions fortes, moment fort au début)…")
    scored = []
    cache = getattr(jury, "cache", None) or {}
    for rank, (clip, login) in enumerate(candidates, offset):
        progress.check()
        prior = 1 / (1 + 0.15 * rank)  # ordre de la présélection (données Twitch)
        path = None
        hit = cache.get(clip.id) if jury is not None else None
        if hit:  # déjà jugé lors d'une recherche récente : rien à refaire
            clip.audio, clip.cached_verdict = hit.get("audio"), hit.get("verdict")
            factor = audio_factor(clip.audio) if clip.audio else 0.8
            scored.append((prior * factor, clip, login, None))
            log.info("  %s · déjà jugé par le Radar", clip.title)
            continue
        try:
            from .jury import quick_transcript
            from .moments import Window, auto_cut
            from .subtitles import SAMPLE_RATE, load_audio

            got = sources[clip.id]()
            if isinstance(got, Window):
                window = got
            else:  # la vidéo du clip lui-même
                length = float(getattr(clip, "duration", 0) or 0)
                window = Window(Path(got), None, length, (0.0, length))
            clip.window, path = window, window.path
            clip.audio = audio_profile(Path(path))
            factor = audio_factor(clip.audio)
            if not window.length:
                window.length = float((clip.audio or {}).get("duration") or 0)
                window.span = (0.0, window.length)
        except progress.Cancelled:
            raise
        except Exception:
            log.warning("Écoute impossible pour %s : gardé sur ses données Twitch", clip.id)
            clip.audio, factor = None, 0.8
        if path:
            try:  # pendant que les extraits suivants se téléchargent : les phrases dites,
                # puis une première découpe complète (que le Radar peut remplacer)
                progress.step("radar", f"Écoute des moments présélectionnés "
                                        f"({rank - offset + 1}/{len(candidates)})")
                clip.window_words = quick_transcript(Path(path), getattr(jury, "language", None))
                clip.cut = auto_cut(window, clip.window_words, load_audio(Path(path)),
                                    SAMPLE_RATE)
            except progress.Cancelled:
                raise
            except Exception:
                log.warning("Découpe automatique impossible pour %s", clip.id, exc_info=True)
        scored.append((prior * factor, clip, login, path))
        if clip.audio:
            log.info("  %s · réaction ×%.1f à %.0f s → %.2f", clip.title, clip.audio["reaction"],
                     clip.audio["peak_at"], prior * factor)
    if jury is None:
        return scored, []
    return _apply_jury(scored, jury)


def _radar_cut(clip, verdict: dict) -> None:
    """Début / fin choisis par le Radar, s'ils sont plausibles (sinon : découpe auto)."""
    from .moments import MIN_LEN, clamp_cut

    start, end = verdict.get("start"), verdict.get("end")
    if start is None or end is None or end - start < MIN_LEN * 0.8:
        return
    window = getattr(clip, "window", None)
    if window is not None:
        clip.cut = clamp_cut(window, start, end)
    else:  # déjà jugé lors d'une recherche récente : l'extrait sera retéléchargé
        clip.cut = (start, end)
    log.info("  Découpe du Radar : %.1f s → %.1f s", *clip.cut)


def _apply_jury(scored: list, jury) -> tuple[list, list]:
    """Combine l'avis de Claude au score. Retourne (clips retenus, clips sous la note
    minimale, gardés en réserve)."""
    from . import jury as jury_mod
    from . import progress

    items = [(clip, path) for _, clip, _, path in scored if path]
    try:
        verdicts = jury(items) if items else {}
    except progress.Cancelled:
        raise
    except Exception as exc:
        log.warning("Radar indisponible (%s) : choix sur le son et les vues", exc)
        verdicts = {}
        if not any(getattr(c, "cached_verdict", None) for _, c, _, _ in scored):
            return scored, []
    kept, below = [], []
    for value, clip, login, path in scored:
        verdict = verdicts.get(clip.id) or getattr(clip, "cached_verdict", None)
        clip.jury = verdict
        if verdict:
            log.info("  Radar : %s → %.1f/10 (%s)", clip.title, verdict["score"], verdict["reason"])
            _radar_cut(clip, verdict)
        entry = (value * jury_mod.factor(verdict), clip, login, path)
        weak = verdict and (verdict["score"] < jury_mod.MIN_SCORE
                            or not verdict.get("standalone", True))
        (below if weak else kept).append(entry)
    if below:
        log.info("Radar : %d clip(s) sous %.1f/10 ou pas clairs sans contexte, sur %d",
                 len(below), jury_mod.MIN_SCORE, len(scored))
    return kept, below
