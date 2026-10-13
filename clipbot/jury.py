"""Claude complète les clips trouvés pour qu'ils soient cohérents, et écrit leur légende.

Pour chaque clip : un extrait de la rediffusion autour du clip Twitch (voir ``moments``),
6 images, les phrases dites avec leur temps, le titre, le streamer et la catégorie. Un seul
appel pour tous les clips de la recherche. Claude choisit le début et la fin (situation →
chute → réaction) et prépare la publication. Il ne note pas et n'écarte aucun clip : ce
sont les plus vus sur Twitch qui sont montés.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("clipbot.jury")

FRAMES = 6

SYSTEM = """Tu es le monteur d'un compte TikTok francophone qui publie les meilleurs
moments de streamers Twitch. Pour chaque clip, tu as un EXTRAIT de la rediffusion autour du
clip Twitch d'origine (souvent mal coupé par le viewer qui l'a fait) : 6 images de
l'extrait (de gauche à droite, avec leur seconde), les phrases dites avec leur début et
leur fin en secondes, le titre donné par les viewers, le streamer et la catégorie.

1) DÉCOUPE : choisis start et end (secondes dans l'extrait) pour que le clip soit COHÉRENT
   pour quelqu'un qui ne connaît pas le streamer : en le regardant une fois, on comprend
   ce qui se passe du début à la fin.
   - garde le moment du clip Twitch d'origine (c'est lui que les viewers ont aimé) et
     ajoute le début ou la fin qui manque ;
   - start : au début de la phrase ou de l'action qui pose la situation — jamais au
     milieu d'une phrase (prends le début d'une ligne [a → b]), sans temps mort avant ;
   - end : après la chute ET la fin de la réaction du streamer (rire, cri, commentaire),
     à la fin d'une phrase, sans traîner ensuite ;
   - entre 10 et 60 s : n'ajoute que ce qui est utile pour comprendre ;
   - s'il n'y a pas de rediffusion, l'extrait EST le clip : tu ne peux que retirer un
     temps mort au début ou à la fin ;
   - reason : en une phrase courte, ce que tu as ajouté ou retiré et pourquoi.
2) PUBLICATION, fidèle à ce que tu vois et entends (n'invente rien) :
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
  graves, violence, contenu sexuel, propos haineux, drogue…)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
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
                "required": ["id", "reason", "hook", "question",
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
    """Mots dits dans l'extrait (avec leur temps), modèle Whisper léger : pour découper."""
    from .subtitles import transcribe

    try:
        return transcribe(video, model_size="base", language=language, beam_size=1,
                          max_seconds=120)
    except Exception:
        log.warning("Transcription rapide impossible pour %s", video.name, exc_info=True)
        return []


def complete(items: list[tuple], *, language: str | None = "fr") -> dict[str, dict]:
    """``items`` = [(clip, chemin de l'extrait)] → {clip.id: {start, end, reason, hook…}}.
    ``clip.window`` et ``clip.window_words`` (voir ``selection.complete``) décrivent
    l'extrait."""
    from concurrent.futures import ThreadPoolExecutor

    from . import llm, progress
    from .moments import timed_lines

    if not items or not llm.available():
        return {}
    with tempfile.TemporaryDirectory(prefix="cliptv-claude-") as tmp:
        def make_sheet(job):
            i, (clip, path) = job
            try:
                return contact_sheet(Path(path), Path(tmp) / f"clip{i}.jpg")
            except Exception:
                log.warning("Images impossibles pour %s", clip.id, exc_info=True)
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            sheets = list(pool.map(make_sheet, enumerate(items, 1)))
        images, blocks = [], []
        for (clip, path), sheet in zip(items, sheets):
            if sheet:
                images.append(sheet)
            window = getattr(clip, "window", None)
            length = window.length if window else clip.duration
            span = window.span if window else (0.0, clip.duration)
            vod = window is not None and window.vod_start is not None
            times = ", ".join(f"{(k + 0.5) * length / FRAMES:.0f} s" for k in range(FRAMES))
            said = getattr(clip, "window_words", None) or []
            blocks.append(
                f"### Clip id={clip.id}\n"
                f"Image : {f'n°{len(images)} (images à {times})' if sheet else '(aucune)'}\n"
                f"Streamer : {clip.broadcaster_name} · catégorie : "
                f"{getattr(clip, 'category', '') or 'inconnue'}\n"
                f"Titre : {clip.title}\n"
                + (f"Extrait de la rediffusion : {length:.0f} s ; le clip Twitch d'origine va "
                   f"de {span[0]:.1f} à {span[1]:.1f} s\n" if vod else
                   f"Pas de rediffusion : l'extrait est le clip Twitch ({length:.0f} s)\n")
                + f"Phrases [début → fin en s] :\n{timed_lines(said) or '(rien de détecté)'}")
        progress.check()
        progress.step("radar", f"Claude complète les {len(items)} clips…")
        prompt = (f"Voici les clips à compléter. Chaque image montre {FRAMES} instants de "
                  "l'extrait, de gauche à droite.\n\n" + "\n\n".join(blocks))
        data = llm.ask_json(system=SYSTEM, prompt=prompt, schema=SCHEMA, images=images,
                            purpose="découpe", effort="medium", timeout=150)
    out = {}
    for row in data.get("clips") or []:
        try:
            out[str(row["id"])] = {
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


def _seconds(value) -> float | None:
    try:
        return round(max(0.0, float(value)), 2)
    except (TypeError, ValueError):
        return None
