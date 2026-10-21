"""Recherche, étapes 2 et 3 : chaque clip trouvé est complété pour être cohérent, puis monté.

1. **Extrait de la rediffusion** autour du clip Twitch (15 s avant, 12 s après, en 160p :
   quelques Mo), téléchargés en parallèle (``moments.fetch_window``) ; sans rediffusion,
   le clip lui-même ;
2. **phrases dites** (Whisper léger) et première découpe automatique : on remonte au début
   de la phrase en cours, on va jusqu'à la fin de la dernière et de la réaction
   (``moments.auto_cut``) ;
3. **Claude** (un seul appel pour tous les clips) lit les phrases, regarde les images et
   ajoute le début ou la fin qui manque pour que le clip se comprenne ; il écrit aussi la
   légende (``jury.complete``). Sans Claude, la découpe automatique est gardée ;
4. **version 1080p** du passage choisi (``moments.final_video``), puis **montage** :
   visage, sous-titres, format vertical, légende (``pipeline.process_clip``).
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("clipbot.selection")


def claude_enabled(opts) -> bool:
    from . import llm

    return bool(getattr(opts, "jury", False)) and llm.available()


def make_clips(found: list, cfg, state, opts, language: str | None = None) -> list[tuple[str, bool]]:
    """[(clip, login)] → clips complétés et montés. Retourne [(clip_id, succès)]."""
    from . import progress
    from .pipeline import Prefetcher, process_clip

    clips = [clip for clip, _ in found]
    prefetch = Prefetcher(cfg, clips)  # extraits légers, en parallèle
    results = []
    try:
        complete(found, {c.id: prefetch.source(c) for c in clips}, opts, language,
                 model=(cfg.whisper_model, cfg.whisper_device))
        prefetch.prepare(clips)  # versions 1080p, pendant le montage du clip précédent
        for i, (clip, login) in enumerate(found, 1):
            progress.clip(i, len(found), f"{login} · {clip.title}")
            log.info("→ %s · %s (%d vues) %s", login, clip.title, clip.view_count, clip.url)
            try:
                ok = process_clip(clip, login, cfg, state, opts, source=prefetch.final(clip))
            except progress.Cancelled:
                raise
            except Exception:
                log.exception("Erreur sur %s", clip.id)
                ok = False
            results.append((clip.id, ok))
    finally:
        prefetch.close()
    return results


def complete(found: list, sources: dict, opts, language: str | None = None,
             model: tuple = ("small", "auto")) -> None:
    """Extrait, phrases et découpe de chaque clip (``clip.cut``) ; Claude complète.
    ``model`` : (modèle Whisper, appareil) des sous-titres : les mots servent au montage."""
    from . import progress
    from .jury import quick_transcript
    from .moments import Window, auto_cut
    from .subtitles import SAMPLE_RATE, load_audio

    items = []
    for i, (clip, _) in enumerate(found, 1):
        progress.check()
        progress.step("radar", f"Écoute du clip {i}/{len(found)} · {clip.title}")
        try:
            got = sources[clip.id]()
            if isinstance(got, Window):
                window = got
            else:  # la vidéo du clip lui-même
                length = float(getattr(clip, "duration", 0) or 0)
                window = Window(Path(got), None, length, (0.0, length))
            clip.window = window
            clip.window_words = quick_transcript(Path(window.path), language,
                                                 model_size=model[0], device=model[1])
            clip.words_model = model[0]
            clip.cut = auto_cut(window, clip.window_words, load_audio(Path(window.path)),
                                SAMPLE_RATE)
            items.append((clip, window.path))
        except progress.Cancelled:
            raise
        except Exception:
            log.warning("Extrait impossible pour %s : découpe automatique impossible",
                        clip.id, exc_info=True)
    if not items or not getattr(opts, "jury", False):
        return
    from . import jury, llm

    if not llm.available():
        claude_missing(items, llm.describe()[1])
        return
    try:
        verdicts = jury.complete(items, language=language)
    except progress.Cancelled:
        raise
    except Exception as exc:
        claude_missing(items, str(exc))
        return
    if not verdicts:
        claude_missing(items, "réponse vide de Claude")
        return
    for clip, _ in items:
        verdict = verdicts.get(clip.id)
        if verdict:
            clip.jury = verdict  # légende, accroche, style… pour le montage
            claude_cut(clip, verdict)


def claude_missing(items: list, reason: str) -> None:
    """Claude indisponible : on le signale (recherche + carte de chaque clip)."""
    from . import progress

    log.warning("Claude indisponible (%s) : découpe automatique gardée", reason)
    progress.warn(f"Claude indisponible, clips découpés sans lui : {reason}"[:300])
    for clip, _ in items:
        clip.claude_missing = reason[:200]


def claude_cut(clip, verdict: dict) -> None:
    """Début / fin choisis par Claude, s'ils sont plausibles (sinon : découpe auto)."""
    from .moments import MIN_LEN, clamp_cut

    start, end = verdict.get("start"), verdict.get("end")
    if start is None or end is None or end - start < MIN_LEN * 0.8:
        return
    window = getattr(clip, "window", None)
    clip.cut = clamp_cut(window, start, end) if window is not None else (start, end)
    log.info("  Claude : %s → %.1f s à %.1f s (%s)", clip.title, *clip.cut,
             verdict.get("reason") or "")
