from clipbot.captions import format_caption
from clipbot.facecam import CAM_ASPECT, Face, cam_crop_box, choose_layout


def test_cam_crop_box_ratio_and_bounds():
    face = Face(x=1650, y=60, w=120, h=120, frame_w=1920, frame_h=1080)
    w, h, x, y = cam_crop_box(face)
    assert abs(w / h - CAM_ASPECT) < 0.02
    assert 0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1080
    assert x <= face.x and face.x + face.w <= x + w   # le visage est dans le cadre
    assert all(v % 2 == 0 for v in (w, h, x, y))


def test_choose_layout():
    assert choose_layout(None) == "crop"
    assert choose_layout(Face(800, 200, 300, 300, 1920, 1080)) == "crop"    # just chatting
    assert choose_layout(Face(1650, 60, 120, 120, 1920, 1080)) == "split"   # facecam


def test_format_caption_dedup_and_credit():
    cap = format_caption("Il ne s'y attendait pas 😭", ["fyp", "#FYP", "just chatting", "#kameto"],
                         "Kamet0")
    lines = cap.splitlines()
    assert lines[0] == "Il ne s'y attendait pas 😭"
    assert lines[1] == "🎮 twitch.tv/kamet0"
    assert lines[2] == "#fyp #justchatting #kameto"


def test_detect_face_never_raises(monkeypatch, tmp_path):
    import sys
    import types

    from clipbot import facecam

    monkeypatch.setitem(sys.modules, "cv2", types.SimpleNamespace(__version__="5.0.0"))
    assert facecam.detect_face(tmp_path / "x.mp4") is None  # OpenCV 5 : pas de cascade

    fake = types.SimpleNamespace(__version__="4.14", CascadeClassifier=object)
    monkeypatch.setitem(sys.modules, "cv2", fake)
    monkeypatch.setattr(facecam, "_detect", lambda *a: 1 / 0)
    assert facecam.detect_face(tmp_path / "x.mp4") is None  # erreur → cadrage par défaut


def test_best_track_prefers_persistent_face():
    from clipbot.facecam import _best_track

    cam = (1700, 100, 80, 100, 0.9)
    frames = [(i * 0.5, [cam] + ([(900, 500, 120, 150, 0.95)] if 4 <= i < 6 else []))
              for i in range(20)]
    best = _best_track(frames)
    assert len(best) == 20 and all(b[0] == 1700 for _, b in best)


def test_best_track_follows_moving_face():
    from clipbot.facecam import _best_track

    frames = [(i * 0.5, [(100 + 40 * i, 300, 300, 400, 0.9)]) for i in range(20)]
    assert len(_best_track(frames)) == 20  # une seule piste malgré le déplacement


def test_smooth_track():
    from clipbot.facecam import smooth_track

    still = [(i * 0.5, 0.5 + (0.01 if i % 2 else -0.01)) for i in range(20)]
    assert len(smooth_track(still)) == 1  # tremblements ignorés : zoom fixe
    moving = [(i * 0.5, 0.2 + 0.03 * i) for i in range(20)]
    moving[7] = (3.5, 0.95)  # détection aberrante
    pts = smooth_track(moving)
    assert len(pts) > 2 and pts[0][1] < pts[-1][1] and max(c for _, c in pts) < 0.8
