"""Génération du titre / des hashtags TikTok avec Claude à partir de la transcription.

Optionnel : nécessite ``pip install anthropic`` et une clé (ANTHROPIC_API_KEY ou
``ant auth login``). En cas d'échec, on retombe sur la légende modèle.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("clipbot.captions")

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


def format_caption(hook: str, hashtags: list[str], channel: str) -> str:
    tags = []
    for t in hashtags:
        t = "#" + t.lstrip("#").replace(" ", "")
        if t.lower() not in (x.lower() for x in tags):
            tags.append(t)
    credit = f"🎮 twitch.tv/{channel.lower()}"
    return f"{hook.strip()}\n{credit}\n{' '.join(tags)}"[:2200]


def generate_caption(*, title: str, channel: str, transcript: str, model: str) -> str | None:
    try:
        import anthropic
    except ImportError:
        log.warning("Paquet anthropic absent : légende IA désactivée (pip install anthropic)")
        return None

    client = anthropic.Anthropic()
    prompt = (
        f"Streamer : {channel}\nTitre du clip : {title}\n\n"
        f"Transcription :\n{transcript or '(pas de parole détectée)'}"
    )
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=2000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            # si le modèle refuse, l'API relance la requête sur un modèle de repli
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIStatusError as exc:
        log.warning("Claude indisponible (%s) : légende modèle utilisée", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("Claude injoignable : légende modèle utilisée")
        return None

    if response.stop_reason != "end_turn":
        log.warning("Légende IA non générée (stop_reason=%s)", response.stop_reason)
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    data = json.loads(text)
    return format_caption(data["hook"], data["hashtags"], channel)
