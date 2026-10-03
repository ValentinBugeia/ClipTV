"""Police des sous-titres : Montserrat Black (licence SIL OFL), téléchargée au besoin."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("clipbot")

FONT_URL = ("https://raw.githubusercontent.com/JulietaUla/Montserrat/master/"
            "fonts/ttf/Montserrat-Black.ttf")


def ensure_font(fonts_dir: Path) -> Path | None:
    """Télécharge Montserrat-Black.ttf si aucun .ttf n'est présent. Retourne le dossier."""
    if fonts_dir.is_dir() and any(fonts_dir.glob("*.ttf")):
        return fonts_dir
    try:
        import requests

        resp = requests.get(FONT_URL, timeout=30)
        resp.raise_for_status()
        fonts_dir.mkdir(parents=True, exist_ok=True)
        (fonts_dir / "Montserrat-Black.ttf").write_bytes(resp.content)
        log.info("Police Montserrat Black téléchargée dans %s", fonts_dir)
        return fonts_dir
    except Exception as exc:  # pas bloquant : libass utilisera une police de repli
        log.warning("Police non téléchargée (%s) : police de repli utilisée", exc)
        return fonts_dir if fonts_dir.is_dir() else None
