"""Téléchargement des clips avec yt-dlp."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("clipbot")

# 1er essai : meilleure version complète en mp4 ; 2e essai si la vidéo arrive muette :
# meilleure vidéo + meilleure piste audio, fusionnées.
FORMATS = ("best[ext=mp4]/best", "bv*+ba/b")


def has_audio(path: Path) -> bool:
    """Le fichier contient-il une piste audio ?"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return "audio" in out.stdout


def _fetch(url: str, dest_dir: Path, clip_id: str, fmt: str) -> Path:
    import yt_dlp

    for old in dest_dir.glob(f"{clip_id}.*"):  # pas de reste d'un essai précédent
        old.unlink()
    opts = {
        "outtmpl": str(dest_dir / f"{clip_id}.%(ext)s"),
        "format": fmt,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    matches = sorted(dest_dir.glob(f"{clip_id}.*"))
    if not matches:
        raise RuntimeError(f"Échec du téléchargement : {url}")
    return next((m for m in matches if m.suffix == ".mp4"), matches[0])


def download_clip(url: str, dest_dir: Path, clip_id: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{clip_id}.mp4"
    if target.exists() and has_audio(target):
        return target
    for fmt in FORMATS:
        path = _fetch(url, dest_dir, clip_id, fmt)
        if has_audio(path):
            return path
        log.warning("Clip %s téléchargé sans son (format %s), nouvel essai…", clip_id, fmt)
    raise RuntimeError("Clip téléchargé sans son : Twitch n'a fourni aucune piste audio")
