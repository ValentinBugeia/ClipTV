"""Génération du titre / des hashtags TikTok avec Claude à partir de la transcription.

Optionnel : nécessite ``pip install anthropic`` et une clé (ANTHROPIC_API_KEY ou
``ant auth login``). En cas d'échec, on retombe sur la légende modèle.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("clipbot.captions")

last_error: str | None = None  # dernier problème avec Claude (affiché dans l'onglet Aide)


def explain_api_error(status: int, message: str) -> str:
    """Erreur de l'API Claude → ce qu'il faut faire."""
    if re.search(r"credit balance|billing|purchase credits", message, re.I):
        return ("Plus de crédit sur ton compte Claude → console.anthropic.com → Billing → "
                "ajoute du crédit (quelques euros suffisent).")
    if status == 401:
        return "Clé Claude refusée → recopie-la dans Comptes → Clés API (elle commence par sk-ant-)."
    if status == 403:
        return "Ta clé Claude n'a pas accès à ce modèle → vérifie ton compte sur console.anthropic.com."
    if status == 404 or re.search(r"model.{0,40}(not found|not exist|invalid|unknown)", message, re.I):
        return f"Modèle Claude indisponible → vérifie CLIPBOT_LLM_MODEL ({message[:120]})."
    if status == 429:
        return "Trop de demandes à Claude pour le moment → ça repartira tout seul."
    if status >= 500 or status == 529:
        return "Claude est surchargé ou en panne → ça repartira tout seul."
    return f"Claude a refusé la demande ({status}) : {message[:160]}"

SYSTEM = """Tu es community manager TikTok spécialisé dans les clips de streamers Twitch.
À partir du titre du clip et de sa transcription, écris une légende courte qui donne
envie de regarder jusqu'au bout : une accroche (max 90 caractères, pas de spoiler de la
chute), puis 4 à 6 hashtags pertinents (jeu, streamer, type de moment, + #fyp).
Reste fidèle au contenu, n'invente pas de faits. Écris dans la langue de la transcription."""

SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "description": "accroche, max 90 caractères"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "hashtags"],
    "additionalProperties": False,
}


MOODS = [  # (mots du titre, emoji) : le premier qui correspond l'emporte
    (r"mdr|ptdr|lol|rire|drôle|marrant|blague|xd", "😂"),
    (r"peur|flipp|horreur|jumpscare|cri|hurl", "😱"),
    (r"rage|énerv|insult|clash|embrouille|vénère|tilt", "😡"),
    (r"fail|raté|rate |chute|tomb|bug|glitch", "💀"),
    (r"maman|daron|mère|père|famille|pleur|triste", "😭"),
    (r"clutch|ace|victoire|win|gagn|incroyable|monstre|insane|record|top ?1", "🔥"),
    (r"love|bisou|crush|cœur|coeur|mignon", "🥰"),
    (r"argent|€|euros|thune|riche", "💸"),
]
FALLBACK_MOODS = ["🔥", "😂", "😱", "💀", "😭", "👀"]


def mood_emoji(title: str, seed: str = "") -> str:
    """Emoji qui colle au titre du clip ; sinon un emoji varié (stable pour un même clip).
    Rien si le titre contient déjà un emoji."""
    import re
    import unicodedata
    from zlib import crc32

    if any(unicodedata.category(c) == "So" for c in title or ""):
        return ""
    low = (title or "").lower()
    for pattern, emoji in MOODS:
        if re.search(pattern, low):
            return emoji
    return FALLBACK_MOODS[crc32((seed or title or "").encode()) % len(FALLBACK_MOODS)]


def credit_emoji(category: str = "") -> str:
    """Emoji du crédit selon la catégorie Twitch."""
    c = (category or "").lower()
    for keys, emoji in ((("music", "dj", "dance"), "🎵"), (("sports",), "⚽"),
                        (("art", "makers"), "🎨"), (("food",), "🍔"),
                        (("just chatting", "irl", "talk", "travel", "asmr"), "🎙️")):
        if any(k in c for k in keys):
            return emoji
    return "🎮"


MAX_HASHTAGS = 8
# toujours utiles pour un compte de clips Twitch francophone : niche FR + découverte
DEFAULT_TAGS = ["twitchfr", "twitch", "streamerfr", "clip", "pourtoi", "fyp"]


def clean_tag(text: str) -> str:
    """« Just Chatting » → « justchatting », « Pokémon » → « pokemon » (format hashtag)."""
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9_]", "", text.lower())


def base_hashtags(channel: str, category: str = "") -> list[str]:
    """Hashtags cohérents pour un clip : streamer, jeu/catégorie, puis niche et découverte."""
    from .twitch import is_non_gaming

    tags = [channel]
    if category:
        tags.append(category)
        tags += ["irl"] if is_non_gaming(category) else ["gaming"]
    return tags + DEFAULT_TAGS


def merge_hashtags(*groups: list[str], limit: int = MAX_HASHTAGS) -> list[str]:
    out: list[str] = []
    for group in groups:
        for t in group:
            t = clean_tag(t.lstrip("#"))
            if t and t not in out:
                out.append(t)
    return ["#" + t for t in out[:limit]]


def format_caption(hook: str, hashtags: list[str], channel: str, category: str = "") -> str:
    """Accroche, crédit du streamer, puis jusqu'à 8 hashtags : ceux choisis pour le contenu
    d'abord, complétés par le streamer, le jeu et les hashtags de niche."""
    base = base_hashtags(channel, category)
    # Claude en donne 4 à 6 : on garde la place du streamer et du jeu dans les 8
    tags = merge_hashtags(hashtags[:6], [channel, category], base)
    credit = f"{credit_emoji(category)} twitch.tv/{channel.lower()}"
    return f"{hook.strip()}\n{credit}\n{' '.join(tags)}"[:2200]


def generate_caption(*, title: str, channel: str, transcript: str, model: str,
                     category: str = "") -> str | None:
    try:
        import anthropic
    except ImportError:
        log.warning("Paquet anthropic absent : légende IA désactivée (pip install anthropic)")
        return None

    global last_error
    client = anthropic.Anthropic()
    prompt = (
        f"Streamer : {channel}\nTitre du clip : {title}\n"
        f"Catégorie Twitch : {category or 'inconnue'}\n\n"
        f"Transcription :\n{transcript or '(pas de parole détectée)'}"
    )
    request = dict(model=model, max_tokens=2000, system=SYSTEM,
                   messages=[{"role": "user", "content": prompt}])
    try:
        try:
            response = client.beta.messages.create(
                **request,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                # si le modèle refuse, l'API relance la requête sur un modèle de repli
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.BadRequestError as exc:
            if not re.search(r"fallback|beta|effort|output_config", exc.message, re.I):
                raise
            # option refusée pour ce compte ou ce modèle : requête simple, même résultat
            log.info("Claude : requête simplifiée (%s)", exc.message[:200])
            response = client.messages.create(
                **request,
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
    except anthropic.APIStatusError as exc:
        last_error = explain_api_error(exc.status_code, getattr(exc, "message", str(exc)))
        log.warning("Claude indisponible (%s) : %s · légende modèle utilisée",
                    exc.status_code, last_error)
        return None
    except anthropic.APIConnectionError:
        last_error = "Claude injoignable (connexion internet ?) → réessaie plus tard."
        log.warning("Claude injoignable : légende modèle utilisée")
        return None
    last_error = None

    if response.stop_reason != "end_turn":
        log.warning("Légende IA non générée (stop_reason=%s)", response.stop_reason)
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    data = json.loads(text)
    return format_caption(data["hook"], data["hashtags"], channel, category)
