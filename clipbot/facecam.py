"""Détection de la facecam / du visage du streamer pour un cadrage automatique.

Nécessite ``opencv-python-headless`` (extra ``pip install -e ".[face]"``).

- Détecteur : **YuNet** (réseau de neurones d'OpenCV, modèle de 230 ko fourni dans
  ``clipbot/models``), bien plus fiable que les cascades de Haar sur les visages de
  trois-quarts, penchés, mal éclairés ou petits (facecam dans un coin). Repli sur Haar
  si YuNet est indisponible.
- On analyse ~2 images par seconde et on **suit** chaque visage d'une image à l'autre :
  le streamer est la piste présente le plus souvent ; un visage qui n'apparaît que
  brièvement dans le jeu est ignoré.
- La piste donne aussi la position du visage au fil du temps : en mode zoom, le
  cadrage le suit en douceur (voir ``smooth_track`` et ``render.build_filter``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

log = logging.getLogger("clipbot.facecam")

# zone facecam du layout "split" : entre 25 % et 33 % de la hauteur selon la taille de
# la facecam dans le stream (petite facecam -> petite zone, plus de place pour le jeu)
CAM_ZONE_MIN, CAM_ZONE_MAX = 0.25, 0.33
CAM_ASPECT = 1080 / 768  # ancien format fixe (2/5), gardé pour compatibilité
MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
DETECT_WIDTH = 1920     # pleine résolution HD : les petites facecams penchées restent détectables
MIN_SCORE = 0.6         # confiance minimale YuNet
# une facecam est un cadre incrusté : visible presque tout le temps et quasi immobile.
# Un visage filmé dans la scène (live IRL, caméra à la main) bouge ou disparaît.
FACECAM_MIN_PRESENCE = 0.6
FACECAM_MAX_JITTER = 0.02
CAMERA_MIN_HEIGHT = 0.18  # visage au-delà : caméra plein écran (just chatting), pas une facecam
# un vrai visage bouge (clignements, parole, expressions) ; une photo du streamer dans
# l'habillage du stream (tableau des scores, avatar) reste figée au pixel près.
# Écart moyen entre deux vignettes 24x24 en niveaux de gris (0-255).
MIN_LIVENESS = 0.8  # photo figée : 0 ; visages réels mesurés : 3 et plus
MIN_FACE = 0.025        # hauteur minimale d'un visage (fraction de la hauteur de l'image)


@dataclass
class Face:
    x: int
    y: int
    w: int
    h: int
    frame_w: int
    frame_h: int
    # position du centre au fil du clip : [(secondes, cx / largeur)]
    track: list[tuple[float, float]] = field(default_factory=list)
    presence: float = 1.0  # part des images analysées où le visage est vu
    jitter: float = 0.0    # déplacement typique du centre (fraction de l'image)

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


def cam_zone_height(face: Face, *, out_h: int = 1920) -> int:
    """Hauteur (px, paire) de la zone facecam en haut de la vidéo verticale."""
    frac = _clamp(0.20 + face.relative_height, CAM_ZONE_MIN, CAM_ZONE_MAX)
    return int(out_h * frac) // 2 * 2


def cam_crop_box(face: Face, *, zoom: float = 2.6, zone_h: int = 768,
                 out_w: int = 1080) -> tuple[int, int, int, int]:
    """Rectangle (w, h, x, y) autour du visage, au ratio de la zone facecam du split."""
    aspect = out_w / zone_h
    h = min(face.h * zoom, face.frame_h)
    w = h * aspect
    if w > face.frame_w:
        w = face.frame_w
        h = w / aspect
    x = _clamp(face.cx - w / 2, 0, face.frame_w - w)
    y = _clamp(face.cy - h / 2.4, 0, face.frame_h - h)  # un peu plus d'espace sous le menton
    even = lambda v: int(v) // 2 * 2  # noqa: E731 - libx264 veut des dimensions paires
    return even(w), even(h), even(x), even(y)


def is_facecam(face: Face) -> bool:
    """Petit visage fixe et toujours présent = facecam incrustée dans le stream."""
    return (face.relative_height < CAMERA_MIN_HEIGHT
            and face.presence >= FACECAM_MIN_PRESENCE
            and face.jitter <= FACECAM_MAX_JITTER)


def choose_layout(face: Face | None, *, allow_split: bool = True) -> str:
    """split (facecam en haut, jeu en bas) seulement pour une vraie facecam ; sinon zoom.

    ``allow_split=False`` pour les catégories sans jeu (IRL, Just Chatting…), où un
    visage est forcément dans la scène filmée.
    """
    if face is not None and allow_split and is_facecam(face):
        return "split"
    return "crop"


def detect_face(video: Path, *, min_hits: float = 0.35) -> Face | None:
    """Visage stable du streamer, ou None. Ne lève jamais : sans détection, le clip
    est rendu avec le cadrage par défaut."""
    try:
        import cv2
    except ImportError:
        log.warning("opencv absent : pas de cadrage auto (pip install opencv-python-headless)")
        return None
    try:
        detector, name = _make_detector(cv2)
        if detector is None:
            log.warning("OpenCV %s sans détecteur de visage : pas de cadrage auto",
                        cv2.__version__)
            return None
        face = _detect(cv2, detector, video, min_hits)
    except Exception:
        log.exception("Détection du visage impossible : cadrage par défaut")
        return None
    log.info("Détection du visage (%s) : %s", name,
             f"{face.w}x{face.h} en ({face.x},{face.y}), présent {face.presence:.0%}, "
             f"mouvement {face.jitter:.1%}" if face else "aucun visage stable")
    return face


def _make_detector(cv2):
    """Fonction frame -> [(x, y, w, h, score)], et nom du détecteur."""
    yunet = None
    if hasattr(cv2, "FaceDetectorYN") and MODEL.exists():
        try:
            yunet = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), MIN_SCORE, 0.3, 50)
        except Exception as exc:  # modèle illisible : repli sur Haar
            log.warning("YuNet indisponible (%s) : détecteur Haar utilisé", exc)
    if yunet is not None:

        def detect(frame):
            h, w = frame.shape[:2]
            yunet.setInputSize((w, h))
            _, faces = yunet.detect(frame)
            if faces is None:
                return []
            return [(float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14]))
                    for f in faces]

        return detect, "YuNet"
    if hasattr(cv2, "CascadeClassifier"):  # retiré d'OpenCV 5
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def detect(frame):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            side = max(int(frame.shape[0] * MIN_FACE), 20)
            return [(float(x), float(y), float(w), float(h), 1.0) for x, y, w, h in
                    cascade.detectMultiScale(gray, 1.1, 6, minSize=(side, side))]

        return detect, "Haar"
    return None, None


def _detect(cv2, detector, video: Path, min_hits: float) -> Face | None:
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    samples = int(min(max(total / fps * 2, 16), 60))  # ~2 images/s, 60 au plus
    scale = min(1.0, DETECT_WIDTH / fw) if fw else 1.0

    frames: list[tuple[float, list[tuple[float, float, float, float, float]]]] = []
    for i in range(samples):
        index = int(total * (i + 0.5) / samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            continue
        if scale < 1:
            frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        boxes = [(x / scale, y / scale, w / scale, h / scale, sc,
                  _thumb(cv2, frame, x, y, w, h))
                 for x, y, w, h, sc in detector(frame) if h / scale >= fh * MIN_FACE]
        frames.append((index / fps, boxes))
    cap.release()
    if not frames:
        return None

    best = _best_track(frames)
    if not best or len(best) < len(frames) * min_hits:
        return None
    cxs = [(b[0] + b[2] / 2) / fw for _, b in best]
    cys = [(b[1] + b[3] / 2) / fh for _, b in best]
    jitter = max(_spread(cxs), _spread(cys))
    return Face(
        x=int(median(b[0] for _, b in best)), y=int(median(b[1] for _, b in best)),
        w=int(median(b[2] for _, b in best)), h=int(median(b[3] for _, b in best)),
        frame_w=fw, frame_h=fh,
        track=[(t, cx) for (t, _), cx in zip(best, cxs)],
        presence=len(best) / len(frames), jitter=jitter,
    )


def _spread(values: list[float]) -> float:
    """Écart typique à la médiane (robuste à une détection aberrante)."""
    m = median(values)
    return median(abs(v - m) for v in values) * 1.4826


def _thumb(cv2, frame, x: float, y: float, w: float, h: float):
    """Vignette 24x24 en niveaux de gris du visage (pour mesurer s'il est vivant)."""
    x0, y0 = max(int(x), 0), max(int(y), 0)
    crop = frame[y0:max(int(y + h), y0 + 1), x0:max(int(x + w), x0 + 1)]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return cv2.resize(gray, (24, 24), interpolation=cv2.INTER_AREA).astype("float32")


def liveness(track) -> float | None:
    """Changement moyen du visage d'une image analysée à l'autre (None si inconnu)."""
    thumbs = [b[5] for _, _, b in track if len(b) > 5 and b[5] is not None]
    if len(thumbs) < 3:
        return None
    diffs = [float(abs(a - b).mean()) for a, b in zip(thumbs, thumbs[1:])]
    return median(diffs)


def _best_track(frames) -> list[tuple[float, tuple]]:
    """Relie les détections d'une image à l'autre et renvoie la piste la plus présente.

    Une détection rejoint la piste dont le dernier visage (vu il y a au plus 4 images)
    est le plus proche, si le centre a bougé de moins d'une largeur de visage.
    """
    tracks: list[list[tuple[int, float, tuple]]] = []  # [(n° d'image, t, box)]
    for n, (t, boxes) in enumerate(frames):
        used: set[int] = set()
        for box in sorted(boxes, key=lambda b: -b[4]):
            cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
            best_i, best_d = None, None
            for i, tr in enumerate(tracks):
                last_n, _, lb = tr[-1]
                if i in used or n - last_n > 4 or last_n == n:
                    continue
                d = ((cx - lb[0] - lb[2] / 2) ** 2 + (cy - lb[1] - lb[3] / 2) ** 2) ** 0.5
                if d < max(lb[2], box[2]) * 1.0 and (best_d is None or d < best_d):
                    best_i, best_d = i, d
            if best_i is None:
                tracks.append([(n, t, box)])
                used.add(len(tracks) - 1)
            else:
                tracks[best_i].append((n, t, box))
                used.add(best_i)
    if not tracks:
        return []
    # un visage figé (photo dans l'habillage) n'est jamais le streamer
    alive = [tr for tr in tracks if (liveness(tr) is None or liveness(tr) >= MIN_LIVENESS)]
    if not alive:
        return []
    # la plus présente ; à égalité, la plus grande (la caméra du streamer)
    best = max(alive, key=lambda tr: (len(tr), median(b[3] for _, _, b in tr)))
    return [(t, b) for _, t, b in best]


def smooth_track(track: list[tuple[float, float]], *, still: float = 0.04,
                 max_points: int = 24) -> list[tuple[float, float]]:
    """Trajectoire lissée du visage pour un zoom qui suit sans trembler.

    Médiane glissante (retire les détections aberrantes) puis moyenne glissante ; si le
    visage bouge de moins de ``still`` (fraction de la largeur), on reste fixe.
    """
    if len(track) < 3:
        return track[:1]
    xs = [c for _, c in track]
    med = [median(xs[max(0, i - 2): i + 3]) for i in range(len(xs))]
    avg = [sum(med[max(0, i - 2): i + 3]) / len(med[max(0, i - 2): i + 3])
           for i in range(len(med))]
    if max(avg) - min(avg) < still:
        return [(track[0][0], median(avg))]
    step = max(1, len(avg) // max_points)
    points = [(track[i][0], avg[i]) for i in range(0, len(avg), step)]
    if points[-1][0] != track[-1][0]:
        points.append((track[-1][0], avg[-1]))
    return points
