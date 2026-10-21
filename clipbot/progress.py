"""Progression du traitement en cours, affichée au centre de l'interface web.

Chaque étape du pipeline signale où elle en est (``step``) ; une recherche (ponctuelle,
pilote automatique ou clip de live) est encadrée par ``begin`` / ``end``.
"""

from __future__ import annotations

import threading
import time

# (clé, titre, explication affichée sous l'étape en cours)
STEPS = [
    ("search", "Recherche des clips les plus vus",
     "Clips des lives diffusés pendant la période choisie, classés par vues."),
    ("radar", "Claude complète et choisit les clips",
     "Extrait de la rediffusion autour de chaque candidat, phrases transcrites ; Claude ajoute "
     "le début ou la fin qui manque, garde les plus forts et écrit la description."),
    ("download", "Téléchargement du clip",
     "Version 1080p du passage choisi, depuis la rediffusion (ou le clip Twitch)."),
    ("face", "Détection du visage et cadrage",
     "Repère la facecam ou le streamer pour choisir le cadrage au format téléphone."),
    ("transcribe", "Transcription de la voix",
     "Whisper écoute le clip pour créer les sous-titres (en général déjà fait pendant "
     "l'écoute du clip ; la 1re fois, téléchargement du modèle : quelques minutes)."),
    ("render", "Montage vertical 9:16",
     "ffmpeg recadre la vidéo et incruste les sous-titres animés."),
    ("caption", "Écriture de la légende",
     "Accroche et hashtags (par Claude s'il est installé)."),
]

_lock = threading.Lock()
_state: dict = {"active": False, "run": 0}
_cancel = threading.Event()
on_tokens = None  # appelé en fin de recherche avec les tokens Claude utilisés


class Cancelled(BaseException):
    """Recherche arrêtée par l'utilisateur.

    Hérite de BaseException (pas d'Exception) pour traverser les ``except Exception`` qui
    protègent chaque clip : l'arrêt doit remonter jusqu'à la boucle de recherche.
    """


def cancel() -> bool:
    """Demande l'arrêt du traitement en cours. Retourne False si rien ne tournait."""
    with _lock:
        if not _state["active"]:
            return False
        _state["detail"] = "Arrêt en cours…"
        _state["stopping"] = True
    _cancel.set()
    return True


def cancelled() -> bool:
    return _cancel.is_set()


def check() -> None:
    """À appeler dans les boucles longues : lève ``Cancelled`` si l'arrêt est demandé."""
    if _cancel.is_set():
        raise Cancelled()


def begin(title: str) -> None:
    _cancel.clear()
    from . import llm

    llm.reset_pause()  # nouvelle recherche : on redonne sa chance à Claude
    with _lock:
        _state.update(active=True, run=_state["run"] + 1, title=title, step=None, detail="",
                      clip="", started=time.time(), message="", ended=None, durations={},
                      step_started=None, stopping=False, tokens=0, warning="")


def warn(text: str) -> None:
    """Alerte affichée pendant la recherche et ajoutée au message de fin (ex. Claude
    indisponible). Une seule alerte gardée : la première."""
    with _lock:
        if not _state.get("warning"):
            _state["warning"] = text


def warning() -> str:
    with _lock:
        return _state.get("warning") or ""


def step(key: str, detail: str = "") -> None:
    check()
    with _lock:
        if not _state["active"]:  # étape hors recherche (ex. clip de live) : on démarre
            _state.update(active=True, run=_state["run"] + 1, title="Traitement d'un clip",
                          clip="", started=time.time(), message="", ended=None, durations={},
                          step_started=None, tokens=0)
        _close_step()
        _state.update(step=key, detail=detail, step_started=time.time())


def _close_step() -> None:
    """Ajoute le temps passé dans l'étape courante (cumulé sur tous les clips)."""
    if _state.get("step") and _state.get("step_started"):
        d = _state.setdefault("durations", {})
        d[_state["step"]] = d.get(_state["step"], 0) + time.time() - _state["step_started"]


def clip(index: int, total: int, title: str) -> None:
    with _lock:
        _state["clip"] = f"Clip {index}/{total} : {title}"


def end(message: str) -> None:
    import logging

    with _lock:
        if not _state["active"]:
            _cancel.clear()
            return
        _close_step()
        if _state.get("warning") and _state["warning"] not in message:
            message = f"{message} · ⚠️ {_state['warning']}"
        _state.update(active=False, step=None, step_started=None, message=message,
                      ended=time.time(), stopping=False)
        tokens = _state.get("tokens", 0)
        spent = ", ".join(f"{k} {v:.0f} s" for k, v in _state.get("durations", {}).items())
    _cancel.clear()
    if tokens and on_tokens:
        try:
            on_tokens(tokens)
        except Exception:
            pass
    if spent:
        logging.getLogger("clipbot").info("Durée par étape : %s", spent)


def snapshot() -> dict:
    with _lock:
        snap = dict(_state)
    snap["durations"] = {k: int(v) for k, v in (snap.get("durations") or {}).items()}
    snap["elapsed"] = int((snap.get("ended") or time.time()) - snap.get("started", time.time())) \
        if snap.get("started") else 0
    return snap


def add_tokens(n: int) -> None:
    """Tokens Claude utilisés pendant la recherche en cours (affichés à la fin)."""
    with _lock:
        _state["tokens"] = _state.get("tokens", 0) + n
