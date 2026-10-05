"""Indicateur « potentiel de vues » d'un clip, avant publication.

Score sur 100 en trois parts :
- **Élan sur Twitch** (40) : vues par heure du clip et combien il dépasse les clips
  habituels du streamer (un vrai moment fort, pas juste une grosse chaîne) ;
- **Format TikTok** (25) : durée (15-35 s idéal), paroles (sous-titres), accroche ;
- **Ton audience** (35) : vues moyennes de TES vidéos TikTok du même streamer et de la
  même catégorie, comparées à ta moyenne. Tant que le compte a moins de 5 vidéos
  reliées à des clips, cette part reste neutre (moitié des points).

Ce n'est pas une prédiction exacte : TikTok reste imprévisible. C'est une aide pour
choisir quels clips publier en premier.
"""

from __future__ import annotations

import json
import math
from statistics import median

MIN_HISTORY = 5   # vidéos TikTok reliées avant de se fier à l'historique du compte
LEVELS = ((65, "fort", "🔥 Fort potentiel"), (40, "moyen", "👍 Potentiel moyen"),
          (0, "faible", "💤 Potentiel faible"))
# note sur 10, couleur de rareté façon objets de jeu vidéo
RARITIES = ((9, "legendary", "Légendaire"), (8, "epic", "Épique"), (6, "rare", "Rare"),
            (4, "uncommon", "Peu commun"), (0, "common", "Commun"))


def history(state) -> dict:
    """Vues de tes vidéos TikTok reliées à un clip, regroupées par streamer et catégorie."""
    with state.lock:
        rows = state.conn.execute(
            """SELECT v.views, c.channel, c.category FROM tiktok_videos v
               JOIN clips c ON c.clip_id = v.clip_id WHERE v.views IS NOT NULL""").fetchall()
    out = {"all": [], "channel": {}, "category": {}}
    for views, channel, category in rows:
        out["all"].append(views)
        out["channel"].setdefault((channel or "").lower(), []).append(views)
        if category:
            out["category"].setdefault(category.lower(), []).append(views)
    return out


def _ratio_points(values: list[int], overall: float, max_points: float) -> float | None:
    """Points selon la moyenne d'un groupe par rapport à la moyenne générale (×0,25 → 0,
    ×1 → moitié, ×4 → tout)."""
    if len(values) < 2 or overall <= 0:
        return None
    ratio = max(sum(values) / len(values), 1) / overall
    return max_points * min(max((math.log(ratio, 4) + 1) / 2, 0), 1)


def score(clip: dict, hist: dict) -> dict:
    """{score, level, label, reasons} pour une ligne de la table clips."""
    try:
        sig = json.loads(clip.get("signals") or "{}")
    except ValueError:
        sig = {}
    reasons: list[str] = []

    # --- élan sur Twitch (40) ---
    vph = float(sig.get("vph") or 0)
    momentum = 30 * min(math.log10(max(vph, 1)) / 3, 1)  # 1000 vues/h → 30
    standout = sig.get("standout")
    if standout:
        momentum += 10 * min(max((standout - 0.5) / 2.5, 0), 1)  # ×3 son habitude → 10
        if standout >= 2:
            reasons.append(f"Clip ×{standout:.1f} au-dessus des clips habituels du streamer")
    else:
        momentum += 5
    reasons.append(f"{vph:.0f} vues/h sur Twitch" if vph else "Vues Twitch inconnues")

    # --- format TikTok (25) ---
    dur = float(sig.get("duration") or 0)
    if 12 <= dur <= 35:
        fmt = 15
        reasons.append(f"Durée idéale ({dur:.0f} s)")
    elif 35 < dur <= 50:
        fmt = 10
    elif dur > 50:
        fmt = 4
        reasons.append(f"Long ({dur:.0f} s) : moins regardé jusqu'au bout")
    else:
        fmt = 7 if dur else 9
    if sig.get("speech"):
        fmt += 5
    else:
        reasons.append("Peu ou pas de paroles")
    if sig.get("hook"):
        fmt += 5

    # --- ton audience (35) ---
    overall = median(hist["all"]) if len(hist["all"]) >= MIN_HISTORY else 0
    if overall:
        ch = _ratio_points(hist["channel"].get((clip.get("channel") or "").lower(), []),
                           overall, 20)
        cat = _ratio_points(hist["category"].get((clip.get("category") or "").lower(), []),
                            overall, 15)
        audience = (ch if ch is not None else 10) + (cat if cat is not None else 7.5)
        if ch is not None and ch >= 14:
            reasons.append(f"Les clips de {clip.get('channel')} marchent bien sur ton compte")
        elif ch is not None and ch <= 6:
            reasons.append(f"Les clips de {clip.get('channel')} font peu de vues chez toi")
        if cat is not None and cat >= 11:
            reasons.append(f"La catégorie {clip.get('category')} marche bien chez toi")
    else:
        audience = 17.5
        reasons.append("Pas encore assez de vidéos publiées pour juger ton audience")

    total = round(min(momentum, 40) + min(fmt, 25) + min(audience, 35))
    level, label = next((lv, lb) for th, lv, lb in LEVELS if total >= th)
    note = round(total / 10, 1)
    rarity, rarity_label = next((r, lb) for th, r, lb in RARITIES if note >= th)
    return {"score": total, "level": level, "label": label, "reasons": reasons,
            "note": note, "rarity": rarity, "rarity_label": rarity_label}


def backfill(cfg, state) -> int:
    """Calcule les indices des clips prêts qui n'en ont pas (préparés avant l'indicateur) :
    durée de la vidéo, paroles (d'après la légende), vues/heure Twitch. Retourne le nombre
    de clips complétés."""
    import logging
    import time
    from pathlib import Path

    from .render import probe_duration

    log = logging.getLogger("clipbot.potential")
    twitch = None
    if cfg.twitch_client_id and cfg.twitch_client_secret:
        from .twitch import TwitchClient

        twitch = TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret)
    done = 0
    for status in ("rendered", "scheduled", "failed"):
        for clip in state.list(status):
            if clip.get("signals") or not clip.get("output_path"):
                continue
            sig: dict = {"hook": False, "speech": True}
            try:
                sig["duration"] = round(probe_duration(Path(clip["output_path"])), 1)
            except Exception:
                pass
            if twitch is not None:
                try:
                    from .twitch import get_clip

                    found = get_clip(twitch, clip["clip_id"])
                    if found:
                        sig["vph"] = round(found.virality(), 1)
                except Exception:
                    log.debug("Vues Twitch indisponibles pour %s", clip["clip_id"])
            state.set_signals(clip["clip_id"], json.dumps(sig))
            # la page se met à jour toute seule (même mécanisme qu'un nouveau clip)
            state._write("UPDATE clips SET updated_at=? WHERE clip_id=?",
                         (int(time.time()), clip["clip_id"]))
            done += 1
    return done
