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


def download_preview(url: str, dest_dir: Path, clip_id: str) -> Path:
    """Version légère du clip (480p), pour l'écoute et le Radar."""
    return download_clip(url, dest_dir, f"{clip_id}-small", PREVIEW_FORMATS)


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
