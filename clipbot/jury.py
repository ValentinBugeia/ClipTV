"""Le Radar (le « juré ») : Claude regarde les clips présélectionnés et dit lesquels méritent TikTok.

Pour chaque clip : 4 images (une planche), ce qui est dit (transcription rapide), le titre,
le streamer et la catégorie. Un seul appel pour tous les clips de la recherche. Claude note
chaque clip sur 10 et explique pourquoi ; les clips trop faibles sont écartés, même avec
beaucoup de vues sur Twitch.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("clipbot.jury")

MIN_SCORE = 6.0      # en dessous (ou incompréhensible sans contexte) : clip en réserve
FRAMES = 6
TRANSCRIPT_MAX = 900  # caractères par clip
MARK_EVERY = 5.0      # repère de temps dans les paroles, toutes les 5 s

SYSTEM = """Tu es le directeur éditorial d'un compte TikTok francophone qui publie les
meilleurs moments de streamers Twitch. Tu vois pour chaque clip 6 images prises à
intervalles réguliers (de gauche à droite), ce qui est dit, le titre donné par les viewers, le streamer et la
catégorie. Note chaque clip sur 10 selon sa capacité à faire des vues sur TikTok auprès de
gens qui NE connaissent PAS le streamer :
- COHÉRENT, c'est le critère n°1 : en le regardant une seule fois, on comprend ce qui se
  passe du début à la fin (la situation est posée, puis la chute arrive). Lis les paroles :
  si elles répondent à quelque chose qu'on n'a pas vu, parlent de gens ou d'événements
  inconnus, ou partent dans tous les sens, le clip n'est PAS compréhensible sans contexte
  (standalone = false) et sa note ne dépasse pas 5 ;
- pas de blague interne, pas la suite d'une histoire commencée avant le clip ;
- une vraie chute ou réaction : fou rire, cri, rage, clash, exploit, malaise, moment absurde ;
- ça accroche dès les premières secondes ;
- le clip contient le début de la situation, la chute ET la réaction du streamer.
  Repère ce qui manque : début coupé (on arrive au milieu d'une phrase ou d'une action),
  dernière phrase coupée (regarde les repères de temps et la fin des paroles par rapport
  à la durée du clip), réaction absente.
  · Si la rediffusion est disponible, ClipTV peut récupérer ce qui manque : indique dans
    add_before / add_after combien de secondes ajouter avant / après (0 à 20, juste ce
    qu'il faut pour comprendre la situation et voir la réaction ; 0 si rien ne manque) et
    note le clip tel qu'il sera une fois complété ;
  · sinon, un clip auquel il manque un morceau a une note basse (4 au plus), dis-le dans
    la raison ;
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
                    "add_before": {"type": "number",
                                   "description": "secondes à ajouter avant (rediffusion)"},
                    "add_after": {"type": "number",
                                  "description": "secondes à ajouter après (rediffusion)"},
                },
                "required": ["id", "score", "standalone", "reason", "hook", "question",
                             "hashtags", "overlay", "reaction", "moderation", "hook_theme",
                             "hook_color", "add_before", "add_after"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def contact_sheet(video: Path, out: Path, frames: int = FRAMES) -> Path:
    """Planche de ``frames`` images réparties sur tout le clip, côte à côte."""
    from .render import probe_duration

    duration = max(probe_duration(video), 1.0)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf",
         f"fps={frames / duration:.4f},scale=320:-2,tile={frames}x1", "-frames:v", "1",
         "-q:v", "4", str(out)],
        check=True, capture_output=True, timeout=120)
    return out


def quick_transcript(video: Path, language: str | None = None) -> str:
    """Ce qui est dit, avec un modèle Whisper léger (rapide) : juste pour juger."""
    from .subtitles import transcribe

    try:
        words = transcribe(video, model_size="base", language=language, beam_size=1,
                           max_seconds=60)
    except Exception:
        log.warning("Transcription rapide impossible pour %s", video.name, exc_info=True)
        return ""
    return timed_text(words)


def timed_text(words: list) -> str:
    """Paroles avec des repères de temps (« [5 s] … ») et l'heure de la dernière parole :
    Claude voit quand ça parle, si la fin est coupée. Trop long : début et fin gardés."""
    parts, mark = [], 0.0
    for w in words:
        if w.start >= mark:
            parts.append(f"[{int(w.start // MARK_EVERY * MARK_EVERY)} s]")
            mark = (w.start // MARK_EVERY + 1) * MARK_EVERY
        parts.append(w.text.strip())
    if not parts:
        return ""
    text = " ".join(parts)
    if len(text) > TRANSCRIPT_MAX:  # la fin compte (chute, phrase coupée) : on la garde
        head = int(TRANSCRIPT_MAX * 0.55)
        text = text[:head] + " … " + text[-(TRANSCRIPT_MAX - head):]
    return f"{text} [dernière parole finie à {words[-1].end:.1f} s]"


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
            said = getattr(clip, "quick_text", None)  # déjà fait pendant les téléchargements
            transcripts.append(said if said is not None else quick_transcript(Path(path), language))
        sheets = list(sheets)
        pool.shutdown()
        for i, ((clip, path), sheet, said) in enumerate(zip(items, sheets, transcripts), 1):
            if sheet:
                images.append(sheet)
            audio = getattr(clip, "audio", None) or {}
            blocks.append(
                f"### Clip id={clip.id}\n"
                f"Image : {f'n°{len(images)} (dans l’ordre des images jointes)' if sheet else '(aucune)'}\n"
                f"Streamer : {clip.broadcaster_name} · catégorie : "
                f"{getattr(clip, 'category', '') or 'inconnue'} · durée {clip.duration:.0f} s\n"
                f"Titre : {clip.title}\n"
                f"Rediffusion : {'disponible' if vod_available(clip) else 'indisponible'}\n"
                f"Pic de son : ×{audio.get('reaction', '?')} à {audio.get('peak_at', '?')} s\n"
                f"Paroles (avec repères de temps) : {said or '(rien de détecté)'}")
        progress.check()
        progress.step("radar", f"Claude regarde les {len(items)} clips présélectionnés…")
        prompt = (f"Voici les clips à juger. Chaque image montre {FRAMES} moments du clip, "
                  "de gauche à droite.\n\n" + "\n\n".join(blocks))
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
                "add_before": _seconds(row.get("add_before")),
                "add_after": _seconds(row.get("add_after"))}
        except (KeyError, TypeError, ValueError):
            continue
    return out


MAX_ADD = 20.0  # secondes récupérables au plus de chaque côté


def vod_available(clip) -> bool:
    return bool(getattr(clip, "video_id", "")) and getattr(clip, "vod_offset", None) is not None


def _seconds(value) -> float:
    try:
        return round(max(0.0, min(float(value or 0), MAX_ADD)), 1)
    except (TypeError, ValueError):
        return 0.0


def factor(verdict: dict | None) -> float:
    """Poids de l'avis de Claude dans le choix final (×0,3 à ×1,9)."""
    if not verdict:
        return 1.0
    f = 0.25 + 1.5 * (verdict["score"] / 10) ** 2
    return f if verdict.get("standalone", True) else f * 0.6
