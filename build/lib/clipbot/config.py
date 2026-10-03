"""Configuration chargée depuis les variables d'environnement (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv est optionnel
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class Config:
    twitch_client_id: str | None = field(default_factory=lambda: _env("TWITCH_CLIENT_ID"))
    twitch_client_secret: str | None = field(default_factory=lambda: _env("TWITCH_CLIENT_SECRET"))

    tiktok_client_key: str | None = field(default_factory=lambda: _env("TIKTOK_CLIENT_KEY"))
    tiktok_client_secret: str | None = field(default_factory=lambda: _env("TIKTOK_CLIENT_SECRET"))
    tiktok_redirect_uri: str | None = field(default_factory=lambda: _env("TIKTOK_REDIRECT_URI"))

    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "auto"))

    llm_model: str = field(default_factory=lambda: _env("CLIPBOT_LLM_MODEL", "claude-opus-5-5"))

    youtube_client_id: str | None = field(default_factory=lambda: _env("YOUTUBE_CLIENT_ID"))
    youtube_client_secret: str | None = field(
        default_factory=lambda: _env("YOUTUBE_CLIENT_SECRET"))
    youtube_privacy: str = field(default_factory=lambda: _env("YOUTUBE_PRIVACY", "private"))

    instagram_user_id: str | None = field(default_factory=lambda: _env("INSTAGRAM_USER_ID"))
    instagram_access_token: str | None = field(
        default_factory=lambda: _env("INSTAGRAM_ACCESS_TOKEN"))
    # graph.instagram.com (Instagram Login) ou graph.facebook.com (Facebook Login)
    instagram_graph_host: str = field(
        default_factory=lambda: _env("INSTAGRAM_GRAPH_HOST", "graph.instagram.com"))

    # plateformes de publication, séparées par des virgules : tiktok,youtube,instagram
    platforms: list[str] = field(default_factory=lambda: [
        p.strip().lower() for p in _env("CLIPBOT_PLATFORMS", "tiktok").split(",") if p.strip()])
    # créneaux de publication (heure locale) pour les clips programmés
    post_slots: list[str] = field(default_factory=lambda: [
        s.strip() for s in _env("CLIPBOT_POST_SLOTS", "12:30,18:00,21:00").split(",")
        if s.strip()])
    timezone: str = field(default_factory=lambda: _env("CLIPBOT_TIMEZONE", "Europe/Paris"))

    # protège l'interface de revue (obligatoire si elle est exposée sur un serveur)
    review_user: str = field(default_factory=lambda: _env("CLIPBOT_REVIEW_USER", "admin"))
    review_password: str | None = field(
        default_factory=lambda: _env("CLIPBOT_REVIEW_PASSWORD"))

    data_dir: Path = field(default_factory=lambda: Path(_env("CLIPBOT_DATA_DIR", "data")))

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "state.sqlite3"

    @property
    def twitch_token_path(self) -> Path:
        return self.data_dir / "twitch_token.json"

    @property
    def tiktok_token_path(self) -> Path:
        return self.data_dir / "tiktok_token.json"

    @property
    def youtube_token_path(self) -> Path:
        return self.data_dir / "youtube_token.json"

    @property
    def instagram_token_path(self) -> Path:
        return self.data_dir / "instagram_token.json"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.downloads_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise SystemExit(
                "Configuration manquante : "
                + ", ".join(n.upper() for n in missing)
                + " (voir .env.example)"
            )
