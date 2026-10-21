"""Carte graphique NVIDIA : transcription (Whisper) et encodage vidéo (NVENC) bien plus
rapides, même résultat (même modèle, même 1080p). Utilisée seulement si tout ce qu'il
faut est là ; sinon tout se fait avec le processeur, comme avant.

- Whisper sur la carte : il faut les bibliothèques CUDA 12 (cuBLAS) et cuDNN 9, installées
  par le lanceur avec pip (paquets ``nvidia-cublas-cu12`` et ``nvidia-cudnn-cu12``) quand
  une carte NVIDIA est détectée. On vérifie qu'elles sont présentes AVANT de s'en servir :
  une bibliothèque manquante peut faire planter tout le programme au lieu de lever une
  erreur.
- Encodage : l'encodeur ``h264_nvenc`` de ffmpeg, testé une fois sur une petite vidéo.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("clipbot.gpu")

WINDOWS = os.name == "nt"
# fichiers indispensables (Windows / Linux) : sans eux, pas de Whisper sur la carte
NEEDED = ({"cublas64_12.dll", "cudnn_ops64_9.dll"} if WINDOWS else
          {"libcublas.so.12", "libcudnn_ops.so.9"})
NVENC = ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "21",
         "-b:v", "0", "-pix_fmt", "yuv420p"]
_disabled: set[str] = set()  # échec en cours de route : on n'y revient plus


def _nvidia_dirs() -> list[Path]:
    """Dossiers des bibliothèques NVIDIA installées avec pip (site-packages/nvidia/*)."""
    dirs = []
    for base in map(Path, sys.path):
        root = base / "nvidia"
        if root.is_dir():
            for sub in root.iterdir():
                for name in ("bin", "lib"):
                    if (sub / name).is_dir():
                        dirs.append(sub / name)
    return dirs


def _search_path() -> list[Path]:
    return _nvidia_dirs() + [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]


@lru_cache(maxsize=1)
def cuda_libraries() -> bool:
    """Bibliothèques CUDA présentes et rendues trouvables pour Whisper."""
    found = {}
    for d in _search_path():
        for name in NEEDED:
            if name not in found and (d / name).exists():
                found[name] = d
    if set(found) != NEEDED:
        return False
    if WINDOWS:
        for d in set(found.values()):
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ.get('PATH', '')}"
            try:
                os.add_dll_directory(str(d))
            except (AttributeError, OSError):
                pass
    else:  # Linux : préchargées, elles seront trouvées par leur nom ensuite
        import ctypes

        for d in set(found.values()):
            for lib in sorted(d.glob("lib*.so.*")):
                try:
                    ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass
    return True


@lru_cache(maxsize=1)
def _cuda_device() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def whisper_device(requested: str = "auto") -> str:
    """« cuda » si la carte NVIDIA peut faire tourner Whisper, sinon « cpu »."""
    if requested not in ("auto", "cuda"):
        return requested
    if "whisper" not in _disabled and _cuda_device() and cuda_libraries():
        return "cuda"
    return "cpu"


def disable(what: str, reason: object) -> None:
    if what not in _disabled:
        log.warning("Carte graphique abandonnée pour %s (%s) : processeur utilisé", what, reason)
    _disabled.add(what)


@lru_cache(maxsize=1)
def _nvenc_works() -> bool:
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=black:s=256x256:d=0.2", *NVENC, "-f", "null", "-"],
            capture_output=True, timeout=30)
        return proc.returncode == 0
    except Exception:
        return False


def video_encoder() -> list[str]:
    """Options d'encodage H.264 : la carte NVIDIA si elle sait le faire, sinon x264."""
    if "nvenc" not in _disabled and _nvenc_works():
        return list(NVENC)
    # veryfast : ~40 % plus rapide que medium, TikTok réencode de toute façon
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def describe() -> str:
    parts = []
    if whisper_device() == "cuda":
        parts.append("transcription sur la carte graphique")
    if video_encoder() == NVENC:
        parts.append("encodage vidéo sur la carte graphique")
    return " · ".join(parts) or "tout sur le processeur"
