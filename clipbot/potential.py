"""Note sur 10 « ce clip va-t-il marcher sur TON compte ? », pour choisir quoi publier.

Basée d'abord sur tes anciens TikToks : une vidéo du même streamer ou de la même
catégorie fait-elle d'habitude plus ou moins de vues que ta moyenne ? 5/10 = un clip
« comme d'habitude » sur ton compte, 7,5 = environ 2× plus de vues attendues, 10 = 4×,
2,5 = 2× moins. L'élan du clip sur Twitch et son format ajustent un peu la note.

Tant que le compte a moins de 5 vidéos avec des vues, la note vient seulement de l'élan
Twitch et du format (estimation de départ).
"""

from __future__ import annotations

import json
import math
import re
from statistics import median

MIN_HISTORY = 5   # vidéos TikTok reliées avant de se fier à l'historique du compte
# note sur 10, couleur de rareté façon objets de jeu vidéo
RARITIES = ((9, "legendary", "Légendaire"), (8, "epic", "Épique"), (6, "rare", "Rare"),
            (4, "uncommon", "Peu commun"), (0, "common", "Commun"))


def history(state) -> dict:
    """Vues de tes vidéos TikTok, par streamer et par catégorie. Une vidéo est rattachée à
    un streamer par son clip d'origine, sinon par le lien twitch.tv/… de sa description."""
    from .captions import clean_tag

    with state.lock:
        rows = state.conn.execute(
            """SELECT v.views, v.description, v.title, c.channel, c.category
               FROM tiktok_videos v LEFT JOIN clips c ON c.clip_id = v.clip_id
               WHERE v.views IS NOT NULL""").fetchall()
        known = [r[0] for r in state.conn.execute(
            "SELECT DISTINCT category FROM clips WHERE category IS NOT NULL")]
    cat_tags = {clean_tag(k): k.lower() for k in known if k}
    out = {"all": [], "channel": {}, "category": {}}
    for views, desc, title, channel, category in rows:
        text = f"{title or ''} {desc or ''}".lower()
        if not channel:
            m = re.search(r"twitch\.tv/(\w+)", text)
            channel = m.group(1) if m else ""
        if not category:
            tags = set(re.findall(r"#(\w+)", text))
            category = next((cat_tags[t] for t in tags if t in cat_tags), "")
        out["all"].append(views)
        if channel:
            out["channel"].setdefault(channel.lower(), []).append(views)
        if category:
            out["category"].setdefault(category.lower(), []).append(views)
    return out


def _group_factor(values: list[int], overall: float) -> float | None:
    """Combien ce groupe fait de vues par rapport à ta moyenne (×), prudent quand il y a
    peu de vidéos : 1 vidéo compte peu, 5 vidéos comptent beaucoup."""
    if not values or overall <= 0:
        return None
    log_ratio = sum(math.log(max(v, 1) / overall) for v in values) / len(values)
    weight = len(values) / (len(values) + 2)
    return math.exp(log_ratio * weight)


def _ratio_points(values: list[int], overall: float, max_points: float) -> float | None:
    """Points selon la moyenne d'un groupe par rapport à la moyenne générale (×0,25 → 0,
    ×1 → moitié, ×4 → tout)."""
    if len(values) < 2 or overall <= 0:
        return None
    ratio = max(sum(values) / len(values), 1) / overall
    return max_points * min(max((math.log(ratio, 4) + 1) / 2, 0), 1)


def _start_score(sig: dict, reasons: list[str]) -> float:
    """Note sur 10 sans historique : élan Twitch (vues/h, clip hors norme) + format."""
    vph = float(sig.get("vph") or 0)
    pts = 30 * min(math.log10(max(vph, 1)) / 3, 1)
    standout = sig.get("standout")
    pts += 10 * min(max((standout - 0.5) / 2.5, 0), 1) if standout else 5
    dur = float(sig.get("duration") or 0)
    pts += 15 if 12 <= dur <= 35 else 10 if 35 < dur <= 50 else 4 if dur > 50 else 8
    pts += 5 if sig.get("speech") else 0
    pts += 5 if sig.get("hook") else 0
    if (sig.get("chat_spike") or 0) >= 3:
        pts += 6
        reasons.append(f"Le chat a explosé au moment du clip (×{sig['chat_spike']:.0f})")
    if (sig.get("reaction") or 0) >= 4 and (sig.get("peak_at") or 99) <= 8:
        pts += 4
        reasons.append(f"Grosse réaction dès {sig['peak_at']:.0f} s")
    return min(pts / 6.5, 10)  # sur 65 points → /10 (l'audience n'est pas encore connue)


NUMERIC = ("vph", "standout", "duration", "chat_spike", "reaction", "peak_at", "talk_rate",
           "hype_words", "jury", "audience_share")


def _clean(sig: dict) -> dict:
    """Indices numériques uniquement là où on attend des nombres (une ancienne version
    enregistrait le type de réaction du Radar, « laugh », à la place de la mesure du son)."""
    out = dict(sig)
    for k in NUMERIC:
        if k in out and not isinstance(out[k], (int, float)) or isinstance(out.get(k), bool):
            out.pop(k, None)
    return out


def score(clip: dict, hist: dict) -> dict:
    """{note, rarity, rarity_label, reasons} pour une ligne de la table clips."""
    try:
        sig = json.loads(clip.get("signals") or "{}")
    except ValueError:
        sig = {}
    sig = _clean(sig)
    reasons: list[str] = []
    channel = (clip.get("channel") or "").lower()
    category = (clip.get("category") or "").lower()
    overall = median(hist["all"]) if len(hist["all"]) >= MIN_HISTORY else 0

    if overall:
        factor = 1.0
        ch = _group_factor(hist["channel"].get(channel, []), overall)
        if ch is not None:
            factor *= ch
            n = len(hist["channel"][channel])
            reasons.append(f"Tes {n} TikTok de {clip.get('channel')} : ×{ch:.1f} ta moyenne")
        else:
            reasons.append(f"Jamais publié de clip de {clip.get('channel')}")
        cat = _group_factor(hist["category"].get(category, []), overall) if category else None
        if cat is not None:
            factor *= cat ** 0.6  # la catégorie compte un peu moins que le streamer
            reasons.append(f"Catégorie {clip.get('category')} : ×{cat:.1f} ta moyenne")
        standout = sig.get("standout")
        if standout:  # un moment vraiment hors norme sur Twitch
            factor *= min(max(standout, 0.5), 4) ** 0.25
            if standout >= 2:
                reasons.append(f"Clip ×{standout:.1f} au-dessus des clips habituels du streamer")
        if (sig.get("chat_spike") or 0) >= 3:
            factor *= 1.2
            reasons.append(f"Le chat a explosé au moment du clip (×{sig['chat_spike']:.0f})")
        if (sig.get("talk_rate") or 0) >= 2.5 or (sig.get("hype_words") or 0) >= 3:
            factor *= 1.1
            reasons.append("Ça parle vite et fort (réactions dans les paroles)")
        if (sig.get("reaction") or 0) >= 4 and (sig.get("peak_at") or 99) <= 8:
            factor *= 1.15
            reasons.append(f"Grosse réaction (son ×{sig['reaction']:.0f}) dès "
                           f"{sig['peak_at']:.0f} s")
        dur = float(sig.get("duration") or 0)
        if dur > 50:
            factor *= 0.8
            reasons.append(f"Long ({dur:.0f} s) : moins regardé jusqu'au bout")
        if sig and not sig.get("speech"):
            factor *= 0.9
        note = 5 + 2.5 * math.log2(max(factor, 1e-3))
        reasons.insert(0, f"Vues attendues : ~{overall * factor:,.0f} (ta moyenne : "
                          f"{overall:,.0f})".replace(",", " "))
    else:
        note = _start_score(sig, reasons)
        reasons.append("Estimation de départ (élan Twitch + format) : moins de "
                       f"{MIN_HISTORY} TikToks avec des vues pour comparer")
    if sig.get("jury") is not None:  # affiché seulement : la note reste basée sur ton compte
        reasons.append(f"Avis du Radar : {sig['jury']:.0f}/10"
                       + (f" — {sig['jury_reason']}" if sig.get("jury_reason") else ""))
    note = round(min(max(note, 0), 10), 1)
    rarity, rarity_label = next((r, lb) for th, r, lb in RARITIES if note >= th)
    return {"note": note, "rarity": rarity, "rarity_label": rarity_label, "reasons": reasons}


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
