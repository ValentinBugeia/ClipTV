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
    def tiktok_token_path(self) -> Path:
        return self.data_dir / "tiktok_token.json"

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
