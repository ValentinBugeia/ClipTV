"""Clés API et mot de passe saisis dans l'interface (page Comptes), stockés dans la base locale.

Évite d'éditer un fichier ``.env`` sur chaque PC : une valeur saisie dans l'interface
remplace celle du ``.env``. Le mot de passe d'accès n'est stocké que sous forme de hash.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from .config import Config

# (variable d'environnement, attribut de Config, libellé, secret ?)
KEYS = [
    ("TWITCH_CLIENT_ID", "twitch_client_id", "Twitch — Client ID", False),
    ("TWITCH_CLIENT_SECRET", "twitch_client_secret", "Twitch — Client secret", True),
    ("TIKTOK_CLIENT_KEY", "tiktok_client_key", "TikTok — Client key", False),
    ("TIKTOK_CLIENT_SECRET", "tiktok_client_secret", "TikTok — Client secret", True),
    ("TIKTOK_REDIRECT_URI", "tiktok_redirect_uri", "TikTok — Redirect URI", False),
    ("YOUTUBE_CLIENT_ID", "youtube_client_id", "YouTube — Client ID", False),
    ("YOUTUBE_CLIENT_SECRET", "youtube_client_secret", "YouTube — Client secret", True),
]
SETTING = "keys"
PASSWORD_SETTING = "password_hash"


def apply_keys(cfg: Config, state) -> None:
    """Applique les clés enregistrées dans l'interface (prioritaires sur le .env)."""
    stored = state.get_settings().get(SETTING, {})
    for env, attr, _, _ in KEYS:
        value = stored.get(env)
        if value:
            os.environ[env] = value
            if attr:
                setattr(cfg, attr, value)


def load_stored_keys(cfg: Config) -> None:
    """Au démarrage d'une commande : applique les clés si la base existe déjà."""
    if cfg.db_path.exists():
        from .state import State

        apply_keys(cfg, State(cfg.db_path))


def save_keys(state, cfg: Config, form: dict[str, str]) -> list[str]:
    """Enregistre les champs remplis (un champ vide garde la valeur actuelle)."""
    stored = dict(state.get_settings().get(SETTING, {}))
    changed = []
    for env, _, label, _ in KEYS:
        value = (form.get(env) or "").strip()
        if value and value != stored.get(env):
            stored[env] = value
            changed.append(label)
    state.save_settings({SETTING: stored})
    apply_keys(cfg, state)
    return changed


def current_value(cfg: Config, env: str, attr: str | None) -> str | None:
    return getattr(cfg, attr) if attr else os.environ.get(env)


# ---------- mot de passe d'accès ----------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"pbkdf2${salt}${digest.hex()}"


def check_password(stored: str, password: str) -> bool:
    try:
        _, salt, expected = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return hmac.compare_digest(digest.hex(), expected)


def lan_address() -> str | None:
    """Adresse IP de ce PC sur le réseau local (aucun paquet n'est envoyé)."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
