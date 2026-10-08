"""``clipbot doctor`` : vérifie l'installation et les connexions avant un premier vrai run.

Contrôles locaux (ffmpeg + libass, police, dépendances Python, créneaux, rendu de
test 9:16 sous-titré) puis, sauf ``--offline``, un appel réel à chaque API configurée
(Twitch, TikTok, YouTube, Instagram, Claude) pour valider les clés et les tokens.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import Config

OK, WARN, FAIL = "ok", "warn", "fail"
ICONS = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}


@dataclass
class Check:
    status: str
    label: str
    detail: str = ""


def _module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_local(cfg: Config, fonts_dir: Path, render: bool = True) -> list[Check]:
    from .pipeline import PLATFORMS
    from .schedule import parse_slots

    out: list[Check] = []
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        out.append(Check(FAIL, "ffmpeg", "ffmpeg/ffprobe introuvable dans le PATH"))
    else:
        filters = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                                 text=True).stdout
        has_ass = any(ln.split()[1:2] == ["ass"] for ln in filters.splitlines() if ln.strip())
        out.append(Check(OK if has_ass else FAIL, "ffmpeg",
                         ffmpeg if has_ass else "compilé sans libass : pas de sous-titres"))

    fonts = sorted(fonts_dir.glob("*.ttf")) if fonts_dir.is_dir() else []
    out.append(Check(OK, "police", ", ".join(f.name for f in fonts)) if fonts else
               Check(WARN, "police", f"aucun .ttf dans {fonts_dir}/ : police de repli utilisée"))

    for mod, label, level in (("yt_dlp", "yt-dlp", FAIL),
                              ("faster_whisper", "faster-whisper", FAIL),
                              ("cv2", "opencv (cadrage auto)", WARN)):
        out.append(Check(OK, label) if _module(mod) else
                     Check(level, label, 'non installé (pip install -e ".[all]")'))

    try:
        cfg.ensure_dirs()
        probe = cfg.data_dir / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        out.append(Check(OK, "dossier de données", str(cfg.data_dir.resolve())))
    except OSError as exc:
        out.append(Check(FAIL, "dossier de données", str(exc)))

    unknown = [p for p in cfg.platforms if p not in PLATFORMS]
    out.append(Check(FAIL, "plateformes", f"inconnues : {', '.join(unknown)}") if unknown else
               Check(OK, "plateformes", ", ".join(cfg.platforms)))
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(cfg.timezone)
        parse_slots(cfg.post_slots)
        out.append(Check(OK, "créneaux", f"{', '.join(cfg.post_slots)} ({cfg.timezone})"))
    except (Exception, SystemExit) as exc:
        out.append(Check(FAIL, "créneaux", str(exc)))

    if render and ffmpeg:
        out.append(check_render(fonts_dir if fonts else None))
    return out


def check_render(fonts_dir: Path | None) -> Check:
    """Rend une vidéo de test 16:9 → 9:16 avec sous-titres et vérifie le résultat."""
    from .render import render_vertical
    from .subtitles import Word, write_ass

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "src.mp4"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=2",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                 "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)],
                check=True, capture_output=True)
            subs = write_ass([Word("Test", 0, 1), Word("cliptv", 1, 2)], tmp / "s.ass")
            out = render_vertical(src, tmp / "out.mp4", layout="blur", subtitles=subs,
                                  fonts_dir=fonts_dir)
            dims = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=p=0", str(out)],
                check=True, capture_output=True, text=True).stdout.strip()
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or b"")
            err = err.decode(errors="replace") if isinstance(err, bytes) else err
            return Check(FAIL, "rendu de test", err.strip()[-300:] or str(exc))
    if dims != "1080,1920":
        return Check(FAIL, "rendu de test", f"dimensions inattendues : {dims}")
    return Check(OK, "rendu de test", "vidéo 1080x1920 sous-titrée générée")


def _online(label: str, fn) -> Check:
    try:
        detail = fn()
        return Check(OK, label, detail or "")
    except SystemExit as exc:  # config ou token manquant
        from .errors import explain

        return Check(FAIL, label, explain(exc))
    except Exception as exc:
        from .errors import explain

        return Check(FAIL, label, explain(exc))


def check_online(cfg: Config, ai: bool = True) -> list[Check]:
    out: list[Check] = []

    if not (cfg.twitch_client_id and cfg.twitch_client_secret):
        out.append(Check(FAIL, "Twitch", "TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET manquants"))
    else:
        from .twitch import TwitchClient, TwitchUserAuth

        def twitch_app():
            client = TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret)
            client.get_broadcaster_id("twitch")
            return "token app OK, API Helix joignable"

        out.append(_online("Twitch (lecture des clips)", twitch_app))
        if cfg.twitch_token_path.exists():
            def twitch_user():
                import requests

                auth = TwitchUserAuth(cfg.twitch_client_id, cfg.twitch_client_secret,
                                      cfg.twitch_token_path)
                resp = requests.get("https://id.twitch.tv/oauth2/validate", timeout=15,
                                    headers={"Authorization": f"OAuth {auth.access_token()}"})
                resp.raise_for_status()
                info = resp.json()
                if "clips:edit" not in info.get("scopes", []):
                    raise RuntimeError("scope clips:edit absent, relance `clipbot twitch-auth`")
                return f"connecté en tant que {info.get('login')}"

            out.append(_online("Twitch (création de clips, watch)", twitch_user))
        else:
            out.append(Check(WARN, "Twitch (création de clips, watch)",
                             "pas connecté : `clipbot twitch-auth` (seulement pour watch)"))

    for platform in cfg.platforms:
        if platform == "tiktok":
            def tiktok():
                from .tiktok import TikTokClient

                cfg.require("tiktok_client_key", "tiktok_client_secret")
                info = TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret,
                                    cfg.tiktok_token_path).user_info()
                return f"compte {info.get('display_name', '?')} (envoi en brouillon)"

            out.append(_online("TikTok", tiktok))
        elif platform == "youtube":
            def youtube():
                from .youtube import YouTubeClient

                cfg.require("youtube_client_id", "youtube_client_secret")
                ch = YouTubeClient(cfg.youtube_client_id, cfg.youtube_client_secret,
                                   cfg.youtube_token_path).channel()
                if not ch:
                    raise RuntimeError("aucune chaîne YouTube sur ce compte Google")
                return f"chaîne {ch.get('title')} (vidéos en {cfg.youtube_privacy})"

            out.append(_online("YouTube", youtube))
        elif platform == "instagram":
            def instagram():
                from .instagram import InstagramClient

                acc = InstagramClient(cfg.instagram_token_path, user_id=cfg.instagram_user_id,
                                      access_token=cfg.instagram_access_token,
                                      host=cfg.instagram_graph_host).account()
                return f"compte @{acc.get('username')}"

            out.append(_online("Instagram", instagram))

    if ai:
        from . import llm

        if not llm.available():
            out.append(Check(WARN, "Claude (abonnement)", llm.describe()[1]))
        else:
            def claude():
                llm.ask_json(system="Test de connexion.", prompt="Réponds {\"ok\": true}.",
                             schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                             timeout=90, purpose="test")
                return "Claude Code répond (ton abonnement)"

            out.append(_online("Claude (abonnement)", claude))
    return out


def run_doctor(cfg: Config, fonts_dir: Path, *, offline: bool = False, render: bool = True,
               ai: bool = True) -> int:
    checks = check_local(cfg, fonts_dir, render=render)
    if not offline:
        checks += check_online(cfg, ai=ai)
    width = max(len(c.label) for c in checks)
    for c in checks:
        print(f"{ICONS[c.status]} {c.label:<{width}}  {c.detail}")
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    print()
    if fails:
        print(f"{fails} problème(s) bloquant(s), {warns} avertissement(s).")
    else:
        print(f"Tout est prêt ({warns} avertissement(s)). Essaie : "
              "clipbot run -c <chaine> --top 1 puis clipbot review")
    return 1 if fails else 0

