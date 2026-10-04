"""Progression du traitement en cours, affichée au centre de l'interface web.

Chaque étape du pipeline signale où elle en est (``step``) ; une recherche (ponctuelle,
pilote automatique ou clip de live) est encadrée par ``begin`` / ``end``.
"""

from __future__ import annotations

import threading
import time

# (clé, titre, explication affichée sous l'étape en cours)
STEPS = [
    ("search", "Recherche des temps forts",
     "Analyse des lives les plus regardés et classement de leurs clips par vues/heure."),
    ("download", "Téléchargement du clip",
     "Récupération de la vidéo depuis Twitch, avec vérification du son."),
    ("face", "Détection du visage et cadrage",
     "Repère la facecam ou le streamer pour choisir le cadrage au format téléphone."),
    ("transcribe", "Transcription de la voix",
     "Whisper écoute le clip pour créer les sous-titres (la 1re fois, téléchargement du "
     "modèle : quelques minutes)."),
    ("render", "Montage vertical 9:16",
     "ffmpeg recadre la vidéo et incruste les sous-titres animés."),
    ("caption", "Écriture de la légende",
     "Accroche et hashtags (par Claude si la clé est configurée)."),
]

_lock = threading.Lock()
_state: dict = {"active": False, "run": 0}


def begin(title: str) -> None:
    with _lock:
        _state.update(active=True, run=_state["run"] + 1, title=title, step=None, detail="",
                      clip="", started=time.time(), message="", ended=None)


def step(key: str, detail: str = "") -> None:
    with _lock:
        if not _state["active"]:  # étape hors recherche (ex. clip de live) : on démarre
            _state.update(active=True, run=_state["run"] + 1, title="Traitement d'un clip",
                          clip="", started=time.time(), message="", ended=None)
        _state.update(step=key, detail=detail)


def clip(index: int, total: int, title: str) -> None:
    with _lock:
        _state["clip"] = f"Clip {index}/{total} : {title}"


def end(message: str) -> None:
    with _lock:
        if _state["active"]:
            _state.update(active=False, step=None, message=message, ended=time.time())


def snapshot() -> dict:
    with _lock:
        snap = dict(_state)
    snap["elapsed"] = int((snap.get("ended") or time.time()) - snap.get("started", time.time())) \
        if snap.get("started") else 0
    return snap
