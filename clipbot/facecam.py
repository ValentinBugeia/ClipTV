"""Détection de la facecam / du visage du streamer pour un cadrage automatique.

Nécessite ``opencv-python-headless`` (extra ``pip install -e ".[face]"``).
On échantillonne quelques images du clip, on y cherche des visages (cascade de Haar
fournie avec OpenCV) et on garde la position médiane si elle est stable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from statistics import median

log = logging.getLogger("clipbot.facecam")

# zone du haut en layout "split" : 1080 x 768 (2/5 de 1920)
CAM_ASPECT = 1080 / 768


@dataclass
class Face:
    x: int
    y: int
    w: int
    h: int
    frame_w: int
    frame_h: int

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def relative_height(self) -> float:
        return self.h / self.frame_h


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


def cam_crop_box(face: Face, *, zoom: float = 2.6) -> tuple[int, int, int, int]:
    """Rectangle (w, h, x, y) autour du visage, au ratio de la zone facecam du split."""
    h = min(face.h * zoom, face.frame_h)
    w = h * CAM_ASPECT
    if w > face.frame_w:
        w = face.frame_w
        h = w / CAM_ASPECT
    x = _clamp(face.cx - w / 2, 0, face.frame_w - w)
    y = _clamp(face.cy - h / 2.4, 0, face.frame_h - h)  # un peu plus d'espace sous le menton
    even = lambda v: int(v) // 2 * 2  # noqa: E731 - libx264 veut des dimensions paires
    return even(w), even(h), even(x), even(y)


def choose_layout(face: Face | None) -> str:
    """crop (zoom plein écran) sans visage ou caméra plein écran, split si facecam."""
    if face is None:
        return "crop"
    if face.relative_height >= 0.18:
        return "crop"
    return "split"


def detect_face(video: Path, *, samples: int = 12, min_hits: float = 0.4) -> Face | None:
    """Visage stable du streamer, ou None. Ne lève jamais : sans détection, le clip
    est simplement rendu en mode « blur »."""
    try:
        import cv2
    except ImportError:
        log.warning("opencv absent : pas de cadrage auto (pip install opencv-python-headless)")
        return None
    if not hasattr(cv2, "CascadeClassifier"):  # retiré d'OpenCV 5
        log.warning("OpenCV %s sans CascadeClassifier : pas de cadrage auto "
                    "(pip install 'opencv-python-headless<5')", cv2.__version__)
        return None
    try:
        return _detect(cv2, video, samples, min_hits)
    except Exception:
        log.exception("Détection du visage impossible : cadrage par défaut")
        return None


def _detect(cv2, video: Path, samples: int, min_hits: float) -> Face | None:
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    found: list[tuple[int, int, int, int]] = []
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        min_side = max(int(fh * 0.04), 24)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6,
                                         minSize=(min_side, min_side))
        if len(faces):
            found.append(tuple(int(v) for v in max(faces, key=lambda f: f[2] * f[3])))
    cap.release()

    if not found or len(found) < samples * min_hits:
        return None
    # on garde les détections proches de la médiane (élimine les visages du jeu)
    mx, my = median(f[0] for f in found), median(f[1] for f in found)
    tol = fw * 0.08
    stable = [f for f in found if abs(f[0] - mx) < tol and abs(f[1] - my) < tol]
    if len(stable) < samples * min_hits:
        return None
    return Face(
        x=int(median(f[0] for f in stable)), y=int(median(f[1] for f in stable)),
        w=int(median(f[2] for f in stable)), h=int(median(f[3] for f in stable)),
        frame_w=fw, frame_h=fh,
    )
