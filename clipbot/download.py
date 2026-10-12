"""Téléchargement des clips avec yt-dlp."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("clipbot")

# 1er essai : meilleure version complète en mp4 ; 2e essai si la vidéo arrive muette :
# meilleure vidéo + meilleure piste audio, fusionnées.
FORMATS = ("best[ext=mp4]/best", "bv*+ba/b")
# version légère pour écouter et juger les candidats (son identique, image suffisante pour
# le Radar) : la version 1080p n'est téléchargée que pour les clips retenus
PREVIEW_FORMATS = ("best[height<=480][ext=mp4]/best[height<=480]/worst[ext=mp4]/worst",
                   "bv*[height<=480]+ba/b")


def has_audio(path: Path) -> bool:
    """Le fichier contient-il une piste audio ?"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return "audio" in out.stdout


def _fetch(url: str, dest_dir: Path, clip_id: str, fmt: str) -> Path:
    """``clip_id`` sert de nom de fichier (« id » ou « id-small » pour la version légère)."""
    import yt_dlp

    from . import progress

    for old in dest_dir.glob(f"{clip_id}.*"):  # pas de reste d'un essai précédent
        old.unlink()
    opts = {
        "outtmpl": str(dest_dir / f"{clip_id}.%(ext)s"),
        "format": fmt,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        # bouton « Arrêter » : interrompt le téléchargement en cours
        "progress_hooks": [lambda _d: progress.check()],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    matches = sorted(dest_dir.glob(f"{clip_id}.*"))
    if not matches:
        raise RuntimeError(f"Échec du téléchargement : {url}")
    return next((m for m in matches if m.suffix == ".mp4"), matches[0])


def download_clip(url: str, dest_dir: Path, clip_id: str, formats=FORMATS) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{clip_id}.mp4"
    if target.exists() and has_audio(target):
        return target
    for fmt in formats:
        path = _fetch(url, dest_dir, clip_id, fmt)
        if has_audio(path):
            return path
        log.warning("Clip %s téléchargé sans son (format %s), nouvel essai…", clip_id, fmt)
    raise RuntimeError("Clip téléchargé sans son : Twitch n'a fourni aucune piste audio")


AUTO_ADD = 6.0  # secondes récupérées sans Claude quand le début ou la fin semble coupé


def download_preview(url: str, dest_dir: Path, clip_id: str) -> Path:
    """Version légère du clip (480p), pour l'écoute et le Radar."""
    return download_clip(url, dest_dir, f"{clip_id}-small", PREVIEW_FORMATS)


def download_final(clip, dest_dir: Path, max_duration: float = 60.0,
                   reference: Path | None = None) -> Path:
    """Version 1080p du clip retenu. S'il lui manque un morceau (avis du Radar, ou sans
    Claude : début ou fin en pleine action à l'écoute) et que la
    rediffusion existe : directement l'extrait complété de la rediffusion (un seul
    téléchargement), sinon le clip Twitch. ``clip.vod_added`` = secondes ajoutées au début.
    La version légère est supprimée ensuite."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    verdict = getattr(clip, "jury", None) or {}
    if verdict:  # le Radar a vu et écouté le clip : il sait ce qui manque
        before, after = verdict.get("add_before") or 0, verdict.get("add_after") or 0
    else:  # sans Claude : début ou fin en pleine action, repérés à l'écoute
        audio = getattr(clip, "audio", None) or {}
        before = AUTO_ADD if audio.get("cut_start") else 0
        after = AUTO_ADD if audio.get("cut_end") else 0
    clip.vod_added = None
    small = dest_dir / f"{clip.id}-small.mp4"
    try:
        if (before or after) and getattr(clip, "video_id", "") and \
                getattr(clip, "vod_offset", None) is not None:
            ref = reference if reference and Path(reference).exists() else \
                download_preview(clip.url, dest_dir, clip.id)
            target = dest_dir / f"{clip.id}.mp4"
            added = extend_from_vod(clip, Path(ref), target, before, after, max_duration)
            if added is not None:
                clip.vod_added = added
                return target
        return download_clip(clip.url, dest_dir, clip.id)
    finally:
        small.unlink(missing_ok=True)


def extend_from_vod(clip, reference: Path, target: Path, before: float, after: float,
                    max_duration: float = 60.0) -> float | None:
    """Clip complété avec la rediffusion : ``before`` s avant et ``after`` s après (ce que
    le Radar a jugé manquant), écrit dans ``target`` (« Refaire le montage » garde la
    version complète). ``reference`` : le clip (même son), pour le retrouver dans
    l'extrait. Retourne les secondes ajoutées au début, ou None en cas d'échec
    (rediffusion supprimée, réservée aux abonnés…)."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    from . import progress
    from .render import probe_duration

    offset, length = getattr(clip, "vod_offset", None), float(clip.duration or 0)
    if not getattr(clip, "video_id", "") or offset is None or length <= 0:
        return None
    after = max(min(after, max_duration - length), 0.0)  # la réaction d'abord
    before = max(min(before, max_duration - length - after, offset), 0.0)
    if before < 1 and after < 1:
        return None
    tmp = target.with_name(f"{clip.id}-vod.mp4")
    tmp.unlink(missing_ok=True)
    opts = {
        "outtmpl": str(tmp),
        "format": "best[height<=1080][ext=mp4]/best[height<=1080]/best",
        "quiet": True,
        "no_warnings": True,
        "download_ranges": download_range_func(None, [(offset - before,
                                                       offset + length + after)]),
        "progress_hooks": [lambda _d: progress.check()],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.twitch.tv/videos/{clip.video_id}"])
        got = probe_duration(tmp)
        if not has_audio(tmp) or got < length + 0.5 * (before + after):
            raise RuntimeError(f"extrait incomplet ({got:.0f} s)")
        from .subtitles import SAMPLE_RATE, load_audio

        at = locate(load_audio(reference), load_audio(tmp), SAMPLE_RATE)
        if at is None:
            raise RuntimeError("le clip n'a pas été retrouvé dans l'extrait")
        before = at  # décalage réel (les repères de Twitch sont approximatifs)
    except progress.Cancelled:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        log.info("Rediffusion indisponible pour %s (%s) : clip d'origine gardé", clip.id, exc)
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(target)
    log.info("Clip complété avec la rediffusion : +%.0f s avant, +%.0f s après", before, after)
    return before


def locate(clip_audio, long_audio, sample_rate: int, step: float = 0.05) -> float | None:
    """Seconde de ``long_audio`` où commence ``clip_audio`` (même son), ou None si on ne
    l'y retrouve pas : compare les enveloppes du volume, fenêtre par fenêtre."""
    import numpy as np

    win = max(int(sample_rate * step), 1)

    def envelope(a):
        n = len(a) // win
        e = np.log1p(1000 * np.sqrt(np.mean(np.square(a[: n * win].reshape(n, win)), axis=1)))
        return e - e.mean()
    small, big = envelope(clip_audio), envelope(long_audio)
    if len(small) < 20 or len(big) < len(small):
        return None
    corr = np.correlate(big, small, mode="valid")
    # normalisation par l'énergie de chaque portion de l'extrait
    sq = np.convolve(np.square(big), np.ones(len(small)), mode="valid")
    means = np.convolve(big, np.ones(len(small)), mode="valid") / len(small)
    var = np.maximum(sq - len(small) * np.square(means), 1e-9)
    score = (corr - means * small.sum()) / np.sqrt(var * np.square(small).sum())
    i = int(np.argmax(score))
    return round(i * step, 2) if score[i] >= 0.7 else None
