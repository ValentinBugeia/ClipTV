"""Style de l'accroche à l'écran, adapté au jeu ou à l'ambiance du clip.

Le Radar choisit un thème (d'après les images et le jeu) et une couleur tirée du jeu ou de
la scène ; sans lui, le thème vient de la catégorie Twitch. Chaque thème a sa police (libres,
téléchargées avec la police des sous-titres) et sa façon d'utiliser la couleur.
"""

from __future__ import annotations

import re

# police, taille relative, inclinaison (°), rôle de la couleur du clip
THEMES = {
    "pop":     {"font": "Montserrat Black", "size": 1.0, "tilt": -2.5, "box": "#FFE600",
                "label": "Pop (encadré jaune)"},
    "comic":   {"font": "Bangers", "size": 1.55, "tilt": -4.0, "box": "#FFFFFF",
                "label": "BD"},
    "cartoon": {"font": "Luckiest Guy", "size": 1.05, "tilt": -3.0, "box": "accent",
                "label": "Cartoon"},
    "action":  {"font": "Anton", "size": 1.45, "tilt": -1.5, "box": "accent",
                "label": "Action / FPS"},
    "horror":  {"font": "Creepster", "size": 1.25, "tilt": 0.0, "box": "#0A0A0A",
                "text": "accent", "label": "Horreur"},
    "retro":   {"font": "Press Start 2P", "size": 0.72, "tilt": 0.0, "box": "#111111",
                "text": "accent", "label": "Rétro / pixel"},
    "neon":    {"font": "Montserrat Black", "size": 1.0, "tilt": -2.0, "box": "#140A24",
                "text": "accent", "label": "Néon"},
}
DEFAULT_ACCENT = {"pop": "#FF4F7B", "comic": "#FF4F7B", "cartoon": "#9B5CFF",
                  "action": "#FF4655", "horror": "#E01E1E", "retro": "#39FF14",
                  "neon": "#00E5FF"}

# sans le Radar : thème d'après la catégorie Twitch (mots du nom de la catégorie)
CATEGORY_THEMES = [
    (r"phasmo|lethal company|outlast|dead by daylight|resident evil|silent hill|horror|"
     r"horreur|fnaf|five nights|amnesia|alien|content warning", "horror"),
    (r"minecraft|terraria|stardew|pok[eé]mon|retro|mario|zelda|undertale", "retro"),
    (r"fortnite|fall guys|rocket league|brawl|among us|roblox|overcooked", "cartoon"),
    (r"valorant|counter|cs2|call of duty|warzone|apex|rainbow|battlefield|escape from|"
     r"pubg|overwatch|the finals|arc raiders", "action"),
    (r"league of legends|teamfight|dota|hearthstone|world of warcraft|elden|souls", "comic"),
    (r"just chatting|discussion|irl|talk|asmr|music|musique|art", "pop"),
]
GAME_ACCENTS = [  # couleurs emblématiques quand le Radar n'en donne pas
    (r"valorant", "#FF4655"), (r"fortnite", "#9D4DFF"), (r"minecraft", "#5BB33C"),
    (r"league of legends|teamfight", "#C8AA6E"), (r"grand theft auto|gta", "#57B846"),
    (r"counter|cs2", "#F0A030"), (r"rocket league", "#1E90FF"), (r"apex", "#DA292A"),
]
HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


def theme_for(category: str) -> str:
    low = (category or "").lower()
    return next((t for pattern, t in CATEGORY_THEMES if re.search(pattern, low)), "pop")


def _luminance(hex_rgb: str) -> float:
    h = hex_rgb.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _darker(hex_rgb: str, f: float = 0.45) -> str:
    h = hex_rgb.lstrip("#")
    return "#" + "".join(f"{int(int(h[i:i + 2], 16) * f):02X}" for i in (0, 2, 4))


def resolve(theme: str | None = None, color: str | None = None, category: str = "") -> dict:
    """{font, size, tilt, box, text, shadow} : couleurs en #RRGGBB."""
    theme = theme if theme in THEMES else theme_for(category)
    t = THEMES[theme]
    accent = None
    if color and HEX.match(color.strip()):
        accent = "#" + color.strip().lstrip("#").upper()
    if not accent:
        low = (category or "").lower()
        accent = next((c for p, c in GAME_ACCENTS if re.search(p, low)), DEFAULT_ACCENT[theme])
    box = accent if t["box"] == "accent" else t["box"]
    if t.get("text") == "accent":
        text = accent
    else:  # texte lisible sur l'encadré : noir sur clair, blanc sur foncé
        text = "#000000" if _luminance(box) > 0.55 else "#FFFFFF"
    if box == accent:
        shadow = "#000000" if _luminance(accent) > 0.35 else "#FFFFFF"
    elif t.get("text") == "accent":
        shadow = _darker(accent)
    else:
        shadow = accent
    return {"theme": theme, "font": t["font"], "size": t["size"], "tilt": t["tilt"],
            "box": box, "text": text, "shadow": shadow}
