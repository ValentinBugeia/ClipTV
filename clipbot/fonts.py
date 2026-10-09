"""Polices (licences libres SIL OFL / Apache), téléchargées au besoin : Montserrat Black
pour les sous-titres, et celles des styles d'accroche (BD, cartoon, action, horreur, rétro)."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("clipbot")

FONT_URL = ("https://raw.githubusercontent.com/JulietaUla/Montserrat/master/"
            "fonts/ttf/Montserrat-Black.ttf")
GF = "https://raw.githubusercontent.com/google/fonts/main/"
HOOK_FONTS = {  # styles d'accroche (voir hookstyle) ; sans elles, police de repli
    "Bangers-Regular.ttf": GF + "ofl/bangers/Bangers-Regular.ttf",
    "Anton-Regular.ttf": GF + "ofl/anton/Anton-Regular.ttf",
    "Creepster-Regular.ttf": GF + "ofl/creepster/Creepster-Regular.ttf",
    "PressStart2P-Regular.ttf": GF + "ofl/pressstart2p/PressStart2P-Regular.ttf",
    "LuckiestGuy-Regular.ttf": GF + "apache/luckiestguy/LuckiestGuy-Regular.ttf",
}


def ensure_font(fonts_dir: Path) -> Path | None:
    """Télécharge les polices manquantes (une seule fois). Retourne le dossier."""
    wanted = {"Montserrat-Black.ttf": FONT_URL, **HOOK_FONTS}
    missing = {name: url for name, url in wanted.items() if not (fonts_dir / name).exists()}
    if "Montserrat-Black.ttf" in missing and any(fonts_dir.glob("Montserrat*.ttf")):
        missing.pop("Montserrat-Black.ttf")  # police déjà fournie sous un autre nom
    if missing:
        try:
            import requests
        except ImportError:
            return fonts_dir if fonts_dir.is_dir() else None
        fonts_dir.mkdir(parents=True, exist_ok=True)
        for name, url in missing.items():
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                (fonts_dir / name).write_bytes(resp.content)
                log.info("Police %s téléchargée dans %s", name, fonts_dir)
            except Exception as exc:  # pas bloquant : libass utilisera une police de repli
                log.warning("Police %s non téléchargée (%s) : police de repli", name, exc)
    return fonts_dir if fonts_dir.is_dir() else None
