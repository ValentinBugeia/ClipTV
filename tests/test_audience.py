import time

from clipbot import audience


def test_general_estimate_and_recommendation():
    assert audience.general_level(0, 3) == 0          # lundi 3h : faible
    assert audience.general_level(0, 20) == 2         # lundi 20h : forte
    assert audience.general_level(2, 15) == 2         # mercredi après-midi
    slots, source = audience.recommended_slots()
    assert source == "l'estimation générale" and len(slots) == 3
    hours = [int(s[:2]) for s in slots]
    assert all(abs(a - b) >= 3 for a in hours for b in hours if a != b)
    assert any(18 <= h <= 22 for h in hours)          # au moins un créneau du soir


def test_personal_data_takes_over():
    now = int(time.time())
    base = now - now % 86400  # minuit UTC
    videos = [{"create_time": base + h * 3600, "views": views}
              for h, views in [(9, 100), (9, 120), (14, 900), (14, 1100), (20, 5000),
                               (20, 4000), (23, 300), (23, 200)]]
    personal = audience.personal_hours(videos, "UTC")
    levels = audience.personal_levels(personal)
    assert levels[20] == 2 and levels[9] == 0
    slots, source = audience.recommended_slots(personal)
    assert source == "tes vidéos" and "20:00" in slots


def test_heatmap_html():
    html = audience.heatmap(["12:30", "18:00"], [], "Europe/Paris", apply_button=True)
    assert "Affluence TikTok par heure" in html and "Utiliser les créneaux conseillés" in html
    assert html.count('class="c slot"') == 14         # 2 créneaux x 7 jours
