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
    assert lines[1].endswith("👇")  # question qui fait commenter
    assert lines[2] == "🎮 twitch.tv/kamet0"  # catégorie inconnue : manette
    # tags du contenu d'abord, puis streamer, et complété jusqu'à 8 hashtags cohérents
    assert lines[3] == "#fyp #justchatting #kameto #kamet0 #twitchfr #twitch #streamerfr #clip"


def test_template_caption_hashtags():
    from datetime import datetime, timezone

    from clipbot.pipeline import Options, template_caption
    from clipbot.twitch import Clip

    clip = Clip(id="c", url="u", title="Billy se fait daronned", broadcaster_name="Nico_La",
                creator_name="x", view_count=1, created_at=datetime.now(timezone.utc),
                duration=30, category="Just Chatting")
    lines = template_caption(Options().caption_template, clip).splitlines()
    assert lines[1].endswith("👇")
    del lines[1]
    assert lines == ["Billy se fait daronned 😭", "🎙️ twitch.tv/nico_la",
                     "#nico_la #justchatting #irl #twitchfr #twitch #streamerfr #clip #pourtoi"]
    game = Clip(**{**clip.__dict__, "category": "Pokémon Légendes"})
    text = template_caption(Options().caption_template, game)
    assert "#pokemonlegendes #gaming" in text and "🎮 twitch.tv/nico_la" in text
    # modèle personnalisé avec ses propres hashtags : laissé tel quel
    assert template_caption("{title} #perso", clip) == "Billy se fait daronned #perso"


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


def test_irl_face_is_not_a_facecam():
    small = dict(x=1650, y=60, w=120, h=120, frame_w=1920, frame_h=1080)
    assert choose_layout(Face(**small)) == "split"                      # facecam fixe
    assert choose_layout(Face(**small, jitter=0.08)) == "crop"          # caméra à la main
    assert choose_layout(Face(**small, presence=0.35)) == "crop"        # passant
    assert choose_layout(Face(**small), allow_split=False) == "crop"    # catégorie IRL


def test_cam_zone_adapts_to_facecam_size():
    from clipbot.facecam import cam_zone_height

    tiny = Face(1700, 60, 40, 40, 1920, 1080)
    big = Face(1500, 60, 200, 200, 1920, 1080)
    assert cam_zone_height(tiny) == 480            # 25 % minimum
    assert cam_zone_height(big) == 632             # 33 % maximum
    w, h, x, y = cam_crop_box(big, zone_h=cam_zone_height(big))
    assert abs(w / h - 1080 / 632) < 0.02          # même ratio que la zone


def test_static_photo_is_not_the_streamer():
    import numpy as np

    from clipbot.facecam import _best_track

    rng = np.random.default_rng(0)
    photo = np.full((24, 24), 120.0, dtype="float32")
    frames = []
    for i in range(20):
        live = rng.uniform(0, 255, (24, 24)).astype("float32")  # visage qui change
        frames.append((i * 0.5, [(100, 100, 150, 180, 0.95, photo),        # photo, plus grande
                                 (1700, 800, 80, 100, 0.9, live)]))        # vraie facecam
    best = _best_track(frames)
    assert best and best[0][1][0] == 1700
    only_photo = [(t, [b for b in boxes if b[0] == 100]) for t, boxes in frames]
    assert _best_track(only_photo) == []  # une photo seule n'est pas une facecam


def test_mood_emoji_varies():
    from clipbot.captions import mood_emoji

    assert mood_emoji("il hurle de peur") == "😱"
    assert mood_emoji("le clutch de fou") == "🔥"
    assert mood_emoji("déjà un emoji 😂") == ""
    picks = {mood_emoji("un titre neutre", f"clip{i}") for i in range(30)}
    assert len(picks) >= 4  # pas toujours le même
