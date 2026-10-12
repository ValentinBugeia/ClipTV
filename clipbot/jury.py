"""Le Radar : Claude regarde les moments présélectionnés, choisit où couper chaque clip
pour qu'il soit complet, et dit lesquels méritent TikTok.

Pour chaque moment : un extrait de la rediffusion autour du clip Twitch (voir
``moments``), 6 images, les phrases dites avec leur temps, le titre, le streamer et la
catégorie. Un seul appel pour tous les moments de la recherche. Claude choisit le début et
la fin (situation → chute → réaction), note le clip ainsi découpé sur 10 et prépare sa
publication ; les clips trop faibles sont écartés, même avec beaucoup de vues sur Twitch.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("clipbot.jury")

MIN_SCORE = 6.0      # en dessous (ou incompréhensible sans contexte) : clip en réserve
FRAMES = 6

SYSTEM = """Tu es le monteur et directeur éditorial d'un compte TikTok francophone qui publie les
meilleurs moments de streamers Twitch. Pour chaque moment, tu as un EXTRAIT de la
rediffusion autour du clip Twitch d'origine (souvent mal coupé par le viewer qui l'a fait) :
6 images de l'extrait (de gauche à droite, avec leur seconde), les phrases dites avec leur
début et leur fin en secondes, le titre donné par les viewers, le streamer et la catégorie.

1) DÉCOUPE : choisis start et end (secondes dans l'extrait) pour faire le meilleur clip
   COMPLET possible :
   - start : au début de la phrase ou de l'action qui pose la situation — jamais au milieu
     d'une phrase (prends le début d'une ligne [a → b]), sans temps mort avant ;
   - end : après la chute ET la fin de la réaction du streamer (rire, cri, commentaire),
     à la fin d'une phrase, sans traîner ensuite ;
   - entre 10 et 60 s, idéalement 20 à 45 s : le plus court possible tant que tout se
     comprend ;
   - le clip Twitch d'origine sert de repère (c'est là que les viewers ont vu le moment
     fort), tu peux en sortir pour compléter. S'il n'y a pas de rediffusion, l'extrait EST
     le clip : tu ne peux que raccourcir.
2) NOTE le clip ainsi découpé sur 10 selon sa capacité à faire des vues sur TikTok auprès
   de gens qui NE connaissent PAS le streamer :
- COHÉRENT, c'est le critère n°1 : en le regardant une seule fois, on comprend ce qui se
  passe du début à la fin (la situation est posée, puis la chute arrive). Lis les paroles :
  si elles répondent à quelque chose qu'on n'a pas vu, parlent de gens ou d'événements
  inconnus, ou partent dans tous les sens, le clip n'est PAS compréhensible sans contexte
  (standalone = false) et sa note ne dépasse pas 5 ;
- pas de blague interne, pas la suite d'une histoire commencée avant le clip ;
- une vraie chute ou réaction : fou rire, cri, rage, clash, exploit, malaise, moment absurde ;
- ça accroche dès les premières secondes ;
- complet : s'il manque encore le début de la situation, la fin d'une phrase ou la
  réaction même avec ta découpe (extrait trop court, pas de rediffusion), note basse (4 au
  plus) et dis-le dans la raison ;
- à éviter : temps mort, attente, écran de pause / pub / alerte de don, musique seule,
  gameplay sans réaction, son ou image inexploitable, contenu choquant ou sexuel.
Sois exigeant : 5 = moyen, 7 = bon, 9 = excellent. Réponds en français, raison en une
phrase courte.

Pour chaque clip noté 3 ou plus, prépare aussi sa publication, fidèle à ce que tu vois et
entends (n'invente rien) :
- hook : accroche de la description, COURTE (max 60 caractères), qui se termine par 1 ou 2
  emojis qui collent au moment (😂 😱 😡 💀 😭 🔥 😳 🤯 👀…), sans dévoiler la chute ;
- question : question très courte aux spectateurs sur CE moment (max 45 caractères), qui
  fait commenter, terminée par un emoji (👇 😭 🤔…) ;
- hashtags : 4 à 6 hashtags pertinents (jeu, streamer, type de moment), sans #fyp ;
- overlay : texte affiché en gros pendant les 3 premières secondes, max 40 caractères,
  intrigant (pas le titre Twitch recopié) ;
- hook_theme : style graphique de l'accroche à l'écran, d'après le jeu et l'ambiance des
  images : pop (défaut, coloré), comic (bande dessinée, humour), cartoon (jeux colorés
  type Fortnite), action (FPS, compétition), horror (jeu d'horreur, peur), retro (pixel,
  Minecraft, jeux rétro), neon (ambiance sombre, soirée, néons) ;
- hook_color : couleur vive emblématique du jeu ou dominante de la scène, en #RRGGBB
  (ex. rouge Valorant #FF4655, violet Fortnite #9D4DFF, vert Minecraft #5BB33C) ;
- reaction : le type de moment fort parmi laugh (fou rire), scream (peur, cri), rage,
  skull (fail, malaise absurde), cry (émotion, gênance), fire (exploit), none ;
- moderation : vide, ou une phrase courte si TikTok risque de limiter la vidéo (insultes
  graves, violence, contenu sexuel, propos haineux, drogue…).
Pour les clips notés moins de 3, laisse ces champs vides."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "number"},
                    "standalone": {"type": "boolean",
                                   "description": "compréhensible sans connaître le streamer"},
                    "reason": {"type": "string"},
                    "hook": {"type": "string"},
                    "question": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "overlay": {"type": "string"},
                    "reaction": {"type": "string",
                                 "enum": ["laugh", "scream", "rage", "skull", "cry", "fire",
                                          "none", ""]},
                    "moderation": {"type": "string"},
                    "hook_theme": {"type": "string",
                                   "enum": ["pop", "comic", "cartoon", "action", "horror",
                                            "retro", "neon", ""]},
                    "hook_color": {"type": "string"},
                    "start": {"type": "number", "description": "début du clip (s dans l'extrait)"},
                    "end": {"type": "number", "description": "fin du clip (s dans l'extrait)"},
                },
                "required": ["id", "score", "standalone", "reason", "hook", "question",
                             "hashtags", "overlay", "reaction", "moderation", "hook_theme",
                             "hook_color", "start", "end"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def contact_sheet(video: Path, out: Path, frames: int = FRAMES) -> Path:
    """Planche de ``frames`` images réparties sur toute la vidéo, côte à côte (image n°i
    vers (i + 0,5) × durée / frames secondes)."""
    from .render import probe_duration

    duration = max(probe_duration(video), 1.0)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf",
         f"fps={frames / duration:.4f},scale=320:-2,tile={frames}x1", "-frames:v", "1",
         "-q:v", "4", str(out)],
        check=True, capture_output=True, timeout=120)
    return out


def quick_transcript(video: Path, language: str | None = None) -> list:
    """Mots dits dans l'extrait (avec leur temps), modèle Whisper léger : pour découper
    et juger."""
    from .subtitles import transcribe

    try:
        return transcribe(video, model_size="base", language=language, beam_size=1,
                          max_seconds=120)
    except Exception:
        log.warning("Transcription rapide impossible pour %s", video.name, exc_info=True)
        return []


def judge(items: list[tuple], *, language: str | None = "fr") -> dict[str, dict]:
    """``items`` = [(clip, chemin de la vidéo)] → {clip.id: {score, standalone, reason}}."""
    from . import llm, progress

    if not items or not llm.available():
        return {}
    with tempfile.TemporaryDirectory(prefix="cliptv-jury-") as tmp:
        from concurrent.futures import ThreadPoolExecutor

        images, blocks = [], []

        def make_sheet(job):  # les planches (ffmpeg) pendant que Whisper transcrit
            i, (clip, path) = job
            try:
                return contact_sheet(Path(path), Path(tmp) / f"clip{i}.jpg")
            except Exception:
                log.warning("Images impossibles pour %s", clip.id, exc_info=True)
                return None
        pool = ThreadPoolExecutor(max_workers=2)
        sheets = pool.map(make_sheet, enumerate(items, 1))
        transcripts = []
        for i, (clip, path) in enumerate(items, 1):
            progress.check()
            progress.step("radar", f"Écoute des clips ({i}/{len(items)})")
            said = getattr(clip, "window_words", None)  # déjà fait pendant les téléchargements
            if said is None:
                said = clip.window_words = quick_transcript(Path(path), language)
            transcripts.append(said)
        sheets = list(sheets)
        pool.shutdown()
        for i, ((clip, path), sheet, said) in enumerate(zip(items, sheets, transcripts), 1):
            if sheet:
                images.append(sheet)
            from .moments import timed_lines

            audio = getattr(clip, "audio", None) or {}
            window = getattr(clip, "window", None)
            length = window.length if window else clip.duration
            span = window.span if window else (0.0, clip.duration)
            vod = window is not None and window.vod_start is not None
            times = ", ".join(f"{(k + 0.5) * length / FRAMES:.0f} s" for k in range(FRAMES))
            clippers = getattr(clip, "clippers", 1) or 1
            blocks.append(
                f"### Moment id={clip.id}\n"
                f"Image : {f'n°{len(images)} (images à {times})' if sheet else '(aucune)'}\n"
                f"Streamer : {clip.broadcaster_name} · catégorie : "
                f"{getattr(clip, 'category', '') or 'inconnue'}\n"
                f"Titre : {clip.title}" + (f" · clippé par {clippers} viewers" if clippers > 1
                                           else "") + "\n"
                + (f"Extrait de la rediffusion : {length:.0f} s ; le clip Twitch d'origine va "
                   f"de {span[0]:.1f} à {span[1]:.1f} s\n" if vod else
                   f"Pas de rediffusion : l'extrait est le clip Twitch ({length:.0f} s)\n")
                + f"Pic de son : ×{audio.get('reaction', '?')} à {audio.get('peak_at', '?')} s\n"
                f"Phrases [début → fin en s] :\n{timed_lines(said) or '(rien de détecté)'}")
        progress.check()
        progress.step("radar", f"Claude regarde les {len(items)} clips présélectionnés…")
        prompt = (f"Voici les moments à découper et juger. Chaque image montre {FRAMES} "
                  "instants de l'extrait, de gauche à droite.\n\n" + "\n\n".join(blocks))
        data = llm.ask_json(system=SYSTEM, prompt=prompt, schema=SCHEMA, images=images,
                            purpose="radar", effort="medium", timeout=150)
    out = {}
    for row in data.get("clips") or []:
        try:
            out[str(row["id"])] = {
                "score": max(0.0, min(float(row["score"]), 10.0)),
                "standalone": bool(row.get("standalone", True)),
                "reason": str(row.get("reason") or "")[:200],
                "hook": str(row.get("hook") or "").strip()[:120],
                "question": str(row.get("question") or "").strip()[:90],
                "hashtags": [str(t) for t in (row.get("hashtags") or [])][:6],
                "overlay": str(row.get("overlay") or "").strip()[:60],
                "reaction": str(row.get("reaction") or ""),
                "moderation": str(row.get("moderation") or "").strip()[:160],
                "hook_theme": str(row.get("hook_theme") or ""),
                "hook_color": str(row.get("hook_color") or ""),
                "start": _seconds(row.get("start")),
                "end": _seconds(row.get("end"))}
        except (KeyError, TypeError, ValueError):
            continue
    return out


CACHE_KEY = "radar_cache"   # avis déjà donnés : un clip n'est jugé qu'une fois
CACHE_TTL = 3 * 86400


def remembered(state) -> dict:
    """{clip_id: {verdict, audio}} des clips jugés ces 3 derniers jours."""
    import time

    now = time.time()
    return {k: v for k, v in (state.get_settings().get(CACHE_KEY) or {}).items()
            if now - v.get("at", 0) < CACHE_TTL}


def remember(state, verdicts: dict, clips) -> None:
    import time

    if not verdicts:
        return
    cache = remembered(state)
    now = int(time.time())
    for clip in clips:
        if clip.id in verdicts:
            cache[clip.id] = {"verdict": verdicts[clip.id], "at": now,
                              "audio": getattr(clip, "audio", None)}
    state.save_settings({CACHE_KEY: cache})


def _seconds(value) -> float | None:
    try:
        return round(max(0.0, float(value)), 2)
    except (TypeError, ValueError):
        return None


def factor(verdict: dict | None) -> float:
    """Poids de l'avis de Claude dans le choix final (×0,3 à ×1,9)."""
    if not verdict:
        return 1.0
    f = 0.25 + 1.5 * (verdict["score"] / 10) ** 2
    return f if verdict.get("standalone", True) else f * 0.6
