"""Téléchargement des clips avec yt-dlp."""

from __future__ import annotations

from pathlib import Path


def download_clip(url: str, dest_dir: Path, clip_id: str) -> Path:
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{clip_id}.mp4"
    if target.exists():
        return target
    opts = {
        "outtmpl": str(dest_dir / f"{clip_id}.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    if not target.exists():
        matches = sorted(dest_dir.glob(f"{clip_id}.*"))
        if not matches:
            raise RuntimeError(f"Échec du téléchargement : {url}")
        return matches[0]
    return target
