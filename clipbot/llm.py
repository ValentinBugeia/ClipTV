"""Appels à Claude par ton abonnement : ClipTV lance ``claude -p`` (Claude Code installé
sur ce PC, en mode non interactif). C'est le quota de ton abonnement qui est utilisé, pas
du crédit API. Toute clé API est retirée de l'environnement de la commande : sinon Claude
Code la prendrait en priorité et facturerait du crédit sans prévenir.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("clipbot.llm")

CLI_MODEL = "sonnet"
# variables qui feraient facturer Claude Code sur l'API au lieu de l'abonnement
API_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
           "CLAUDE_CODE_USE_VERTEX")


class ClaudeError(RuntimeError):
    """Claude indisponible : le message dit quoi faire."""


def cli_path() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for p in (home / ".local/bin/claude", home / ".claude/local/claude",
              home / ".npm-global/bin/claude", Path("/usr/local/bin/claude")):
        if p.exists():
            return str(p)
    return None


def available() -> bool:
    return cli_path() is not None


def describe() -> tuple[bool, str]:
    """(disponible, explication) pour les pages Comptes et Aide."""
    if available():
        return True, "Claude Code trouvé sur ce PC : ton abonnement est utilisé (pas de crédit API)"
    return False, ("Claude Code introuvable sur ce PC → installe-le "
                   "(curl -fsSL https://claude.ai/install.sh | bash) puis lance « claude » "
                   "une fois pour te connecter")


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ClaudeError(f"Réponse de Claude illisible : {text[:160]}")
    return json.loads(text[start:end + 1])


def ask_json(*, system: str, prompt: str, schema: dict, images: list[Path] = (),
             timeout: float = 300, effort: str = "low") -> dict:
    """Pose la question à Claude et renvoie sa réponse JSON (conforme à ``schema``)."""
    return _ask_cli(system, prompt, schema, list(images), timeout, effort)


# options récentes de Claude Code : retirées si la version installée ne les connaît pas
FAST_FLAGS = ["--tools", "", "--no-session-persistence"]


def _ask_cli(system: str, prompt: str, schema: dict, images: list[Path], timeout: float,
             effort: str = "low") -> dict:
    """Un seul message (texte + images intégrées), un seul tour, aucun outil : rapide."""
    import base64

    exe = cli_path()
    if not exe:
        raise ClaudeError(describe()[1])
    env = {k: v for k, v in os.environ.items() if k not in API_ENV}
    content: list = []
    for p in images:
        media = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        content.append({"type": "image", "source": {"type": "base64", "media_type": media,
                        "data": base64.b64encode(p.read_bytes()).decode()}})
    content.append({"type": "text", "text": prompt + (
        "\n\nRéponds UNIQUEMENT avec un objet JSON conforme à ce schéma, sans texte autour :\n"
        + json.dumps(schema, ensure_ascii=False))})
    message = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
    base = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--verbose", "--model", CLI_MODEL, "--append-system-prompt", system]
    attempts = [base + FAST_FLAGS + ["--effort", effort], base + FAST_FLAGS, base]
    with tempfile.TemporaryDirectory(prefix="cliptv-claude-") as cwd:
        for cmd in attempts:
            try:
                proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                                      timeout=timeout, input=message + "\n")
            except subprocess.TimeoutExpired:
                raise ClaudeError("Claude Code met trop de temps à répondre → réessaie plus tard.")
            if not re.search(r"unknown option|unknown argument|invalid choice",
                             proc.stderr or "", re.I):
                break  # sinon : ancienne version de Claude Code, on retire des options
    data: dict = {}
    for line in (proc.stdout or "").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("type") == "result":
            data = item
    result = data.get("result") or ""
    if proc.returncode != 0 or data.get("is_error") or not data:
        raw = f"{result} {proc.stderr or ''}" if data else f"{proc.stdout or ''} {proc.stderr or ''}"
        detail = " ".join(raw.split())[:220]
        log.warning("Claude Code (code %s) : %s", proc.returncode, detail)
        if re.search(r"/login|not logged|invalid api key|authenticat", raw, re.I):
            raise ClaudeError("Claude Code n'est pas connecté → ouvre un terminal, tape "
                              "« claude » puis /login avec ton compte Claude "
                              f"(réponse de Claude Code : {detail})")
        if re.search(r"usage limit|limit reached|rate limit|quota", raw, re.I):
            raise ClaudeError("Limite de ton abonnement Claude atteinte pour le moment → "
                              "ça repartira à la réinitialisation du quota.")
        raise ClaudeError(f"Claude Code a échoué : {detail}")
    return _extract_json(result)
