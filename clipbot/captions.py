"""Génération du titre / des hashtags TikTok avec Claude à partir de la transcription.

Optionnel : passe par ton abonnement Claude (Claude Code installé sur ce PC). En cas
d'échec, on retombe sur la légende modèle.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("clipbot.captions")

last_error: str | None = None  # dernier problème avec Claude (affiché dans l'onglet Aide)


SYSTEM = """Tu es community manager TikTok spécialisé dans les clips de streamers Twitch.
À partir du titre du clip et de sa transcription, écris une légende courte qui donne
envie de regarder jusqu'au bout : une accroche (max 90 caractères, pas de spoiler de la
chute), une question courte qui fait commenter et qui porte précisément sur ce qui se
passe dans CE clip (ce que dit ou fait le streamer), puis 4 à 6 hashtags pertinents
(jeu, streamer, type de moment, + #fyp). Pas de question générique ni hors sujet.
Reste fidèle au contenu, n'invente pas de faits. Écris dans la langue de la transcription."""

SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "description": "accroche, max 90 caractères"},
        "question": {"type": "string",
                     "description": "question aux spectateurs sur CE clip, max 60 caractères"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "question", "hashtags"],
    "additionalProperties": False,
}


MOODS = [  # (mots du titre, emoji) : le premier qui correspond l'emporte (débuts de mots)
    (r"mdr|ptdr|lol\b|rire|rigol|drôle|marrant|blague|xd\b", "😂"),
    (r"peur|flipp|horreur|jumpscare|cri(?:s|e|é|er|ent)?\b|hurl", "😱"),
    (r"rage\b|rageu|énerv|insult|clash|embrouille|vénère|tilt", "😡"),
    (r"fail|raté|rate\b|chute|tomb[eé]|bug\b|glitch", "💀"),
    (r"maman|daron|mère\b|père\b|famille|pleur|triste", "😭"),
    (r"clutch|ace\b|victoire|win\b|gagn|incroyable|monstre|insane|record|top ?1\b", "🔥"),
    (r"love\b|bisou|crush|cœur|coeur|mignon", "🥰"),
    (r"argent|\d+ ?€|euros|thune|riche", "💸"),
]
FALLBACK_MOODS = ["🔥", "😂", "😱", "💀", "😭", "👀"]


def title_mood(title: str) -> str:
    """Ambiance annoncée par le titre (emoji), ou "" si le titre n'en dit rien."""
    import re

    low = (title or "").lower()
    for pattern, emoji in MOODS:
        if re.search(r"(?<!\w)(?:" + pattern + ")", low):
            return emoji
    return ""


def mood_emoji(title: str, seed: str = "") -> str:
    """Emoji qui colle au titre du clip ; sinon un emoji varié (stable pour un même clip).
    Rien si le titre contient déjà un emoji."""
    import re
    import unicodedata
    from zlib import crc32

    if any(unicodedata.category(c) == "So" for c in title or ""):
        return ""
    return title_mood(title) or FALLBACK_MOODS[crc32((seed or title or "").encode()) % len(FALLBACK_MOODS)]


def credit_emoji(category: str = "") -> str:
    """Emoji du crédit selon la catégorie Twitch."""
    c = (category or "").lower()
    for keys, emoji in ((("music", "dj", "dance"), "🎵"), (("sports",), "⚽"),
                        (("art", "makers"), "🎨"), (("food",), "🍔"),
                        (("just chatting", "irl", "talk", "travel", "asmr"), "🎙️")):
        if any(k in c for k in keys):
            return emoji
    return "🎮"


# une question en fin de légende fait commenter ; les commentaires font monter la vidéo
# questions par ambiance : utilisées seulement quand le titre annonce clairement cette
# ambiance (sinon une question neutre, qui va avec n'importe quel clip)
CTAS = {
    "😂": ["Tu aurais tenu sans rire ? 😭", "Note ce fou rire sur 10 👇"],
    "😱": ["T'aurais eu peur aussi ? 👇", "T'aurais réagi comment ? 😭"],
    "😡": ["Raison de s'énerver ou pas ? 👇", "Team calme ou team rage ? 👇"],
    "💀": ["T'aurais fait mieux ? 👇", "Le pire fail de la semaine ? 💀"],
    "🔥": ["Note ce moment sur 10 🔥", "T'aurais fait pareil ? 👇"],
}
GENERIC_CTAS = ["T'en penses quoi ? 👇", "Tu l'avais vu passer en live ? 👇",
                "Ton avis en commentaire 👇", "Note ce moment sur 10 👇"]


def call_to_action(mood: str = "", seed: str = "") -> str:
    """Question qui pousse à commenter (stable par clip). ``mood`` : ambiance certaine du
    clip (title_mood), jamais un emoji tiré au hasard."""
    from zlib import crc32

    options = CTAS.get(mood) or GENERIC_CTAS
    return options[crc32(seed.encode()) % len(options)]


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


def format_caption(hook: str, hashtags: list[str], channel: str, category: str = "",
                   question: str = "", tiktok: str | None = None) -> str:
    """Accroche, crédit du streamer, puis jusqu'à 8 hashtags : ceux choisis pour le contenu
    d'abord, complétés par le streamer, le jeu et les hashtags de niche."""
    base = base_hashtags(channel, category)
    # Claude en donne 4 à 6 : on garde la place du streamer et du jeu dans les 8
    tags = merge_hashtags(hashtags[:6], [channel, category], base)
    credit = f"{credit_emoji(category)} twitch.tv/{channel.lower()}"
    if tiktok:  # le streamer est prévenu s'il est mentionné : like, repost possibles
        credit += f" · @{tiktok}"
    hook = hook.strip()
    question = (question or "").strip()
    if hook.endswith("?"):
        cta = ""
    else:
        cta = "\n" + (question or call_to_action(title_mood(hook), seed=hook))
    return f"{hook}{cta}\n{credit}\n{' '.join(tags)}"[:2200]


def generate_caption(*, title: str, channel: str, transcript: str, category: str = "",
                     tiktok: str | None = None) -> str | None:
    """Légende écrite par Claude (ton abonnement, via Claude Code). None si indisponible :
    la légende modèle est alors utilisée."""
    global last_error
    from . import llm

    if not llm.available():
        return None
    prompt = (
        f"Streamer : {channel}\nTitre du clip : {title}\n"
        f"Catégorie Twitch : {category or 'inconnue'}\n\n"
        f"Transcription :\n{transcript or '(pas de parole détectée)'}"
    )
    try:
        data = llm.ask_json(system=SYSTEM, prompt=prompt, schema=SCHEMA)
    except llm.ClaudeError as exc:
        last_error = str(exc)
        log.warning("Claude indisponible : %s · légende modèle utilisée", exc)
        return None
    last_error = None
    return format_caption(data["hook"], data.get("hashtags") or [], channel, category,
                          question=data.get("question", ""), tiktok=tiktok)
