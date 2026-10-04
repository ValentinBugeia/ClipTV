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

    global last_error
    client = anthropic.Anthropic()
    prompt = (
        f"Streamer : {channel}\nTitre du clip : {title}\n\n"
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
    return format_caption(data["hook"], data["hashtags"], channel)
