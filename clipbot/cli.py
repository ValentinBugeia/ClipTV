"""cliptv : clips Twitch viraux → format vertical sous-titré → TikTok / YouTube Shorts / Reels."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .config import Config
from .pipeline import Options

log = logging.getLogger("clipbot")


def options_from_args(args) -> Options:
    fonts_dir = Path(args.fonts_dir) if args.fonts_dir and Path(args.fonts_dir).is_dir() else None
    return Options(
        layout=args.layout,
        language=args.language,
        subtitles=not args.no_subs,
        font=args.font,
        fonts_dir=fonts_dir,
        highlight=args.highlight,
        max_duration=args.max_duration,
        caption_template=getattr(args, "caption", Options.caption_template),
        ai_caption=getattr(args, "ai_caption", False),
        publish=getattr(args, "publish", False),
        schedule=getattr(args, "schedule", False),
        platforms=getattr(args, "platform", None) or [],
        mode=getattr(args, "mode", "draft"),
        privacy=getattr(args, "privacy", "SELF_ONLY"),
    )


def _channels(given: list[str] | None, env: str) -> list[str]:
    """Chaînes passées en argument, sinon lues dans la variable d'environnement (Docker)."""
    import os
    import re

    raw = given or re.split(r"[\s,]+", os.environ.get(env, ""))
    channels = [c.strip().lower() for c in raw if c.strip()]
    if not channels:
        raise SystemExit(f"Aucune chaîne : passe-la en argument ou définis {env}")
    return channels


def cmd_run(args, cfg: Config) -> int:
    from .state import State
    from .twitch import TwitchClient

    import os

    if args.channel or os.environ.get("CLIPBOT_CHANNELS", "").strip():
        args.channel = _channels(args.channel, "CLIPBOT_CHANNELS")
    else:
        args.channel = []  # pas de chaîne : découverte automatique des temps forts
    cfg.require("twitch_client_id", "twitch_client_secret")
    cfg.ensure_dirs()
    opts = options_from_args(args)
    state = State(cfg.db_path)
    twitch = TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret)

    while True:
        if not args.every:
            _run_once(args, cfg, opts, state, twitch)
            return 0
        try:
            _run_once(args, cfg, opts, state, twitch)
        except Exception:  # en mode serveur, une panne Twitch ne doit pas tout arrêter
            log.exception("Passage échoué")
        log.info("Prochain passage dans %d min…", args.every)
        time.sleep(args.every * 60)


def _run_once(args, cfg: Config, opts: Options, state, twitch) -> None:
    from .discover import run_discovery
    from .pipeline import run_channels

    if not args.channel:
        run_discovery(cfg, state, opts, twitch, language=args.discover_language or None,
                      streamers=args.streamers, hours=args.hours, top=args.top,
                      min_views=args.min_views)
        return
    run_channels(args.channel, cfg, state, opts, twitch, hours=args.hours, top=args.top,
                 min_views=args.min_views)


def cmd_watch(args, cfg: Config) -> int:
    import threading

    from .state import State
    from .twitch import TwitchClient, TwitchUserAuth
    from .watcher import WatchParams, watch_channel

    channels = _channels(args.channel, "CLIPBOT_WATCH_CHANNELS")
    cfg.require("twitch_client_id", "twitch_client_secret")
    cfg.ensure_dirs()
    opts = options_from_args(args)
    state = State(cfg.db_path)
    auth = TwitchUserAuth(cfg.twitch_client_id, cfg.twitch_client_secret, cfg.twitch_token_path)
    auth.access_token()  # échoue tout de suite si `twitch-auth` n'a pas été fait
    params = WatchParams(ratio=args.ratio, min_rate=args.min_rate, cooldown=args.cooldown,
                         forever=args.forever or len(channels) > 1)
    # un thread par chaîne (plusieurs lives en parallèle), chacun attend son prochain live
    threads = [threading.Thread(
        target=watch_channel, name=c, daemon=True,
        args=(c, cfg, state, opts, TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret),
              auth, params))
        for c in channels]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_render(args, cfg: Config) -> int:
    from .pipeline import render_video

    src = Path(args.input)
    dst = Path(args.output) if args.output else src.with_name(src.stem + "_vertical.mp4")
    render_video(src, dst, cfg, options_from_args(args))
    print(dst)
    return 0


def cmd_review(args, cfg: Config) -> int:
    import threading

    from .autopilot import Autopilot, apply_settings, load_settings
    from .review import make_server
    from .schedule import run_publisher
    from .state import State

    fonts_dir = Path(args.fonts_dir) if Path(args.fonts_dir).is_dir() else None
    # options de rendu utilisées par le pilote auto et les recherches lancées du navigateur
    opts = Options(mode=args.mode, privacy=args.privacy, platforms=args.platform or [],
                   fonts_dir=fonts_dir, language=args.language)
    if args.host not in ("127.0.0.1", "localhost") and not cfg.review_password:
        log.warning("Interface exposée sur %s SANS mot de passe : "
                    "définis CLIPBOT_REVIEW_PASSWORD", args.host)
    cfg.ensure_dirs()
    state = State(cfg.db_path)
    apply_settings(cfg, load_settings(state, cfg))  # réglages enregistrés depuis l'interface
    autopilot = Autopilot(cfg, state, Options(**{**opts.__dict__, "platforms": []}))
    autopilot.start()
    server = make_server(cfg, opts, host=args.host, port=args.port, state=state,
                         autopilot=autopilot)
    if not args.no_publisher:  # publie les clips programmés à l'heure
        threading.Thread(target=run_publisher, args=(state, cfg, opts), daemon=True).start()
    print(f"cliptv : http://{args.host}:{args.port}  (Ctrl+C pour quitter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        autopilot.shutdown()
    return 0


def cmd_publisher(args, cfg: Config) -> int:
    from .schedule import publish_due, run_publisher
    from .state import State

    cfg.ensure_dirs()
    opts = Options(mode=args.mode, privacy=args.privacy, platforms=args.platform or [])
    state = State(cfg.db_path)
    if args.once:
        print(f"{publish_due(state, cfg, opts)} clip(s) publié(s)")
        return 0
    try:
        run_publisher(state, cfg, opts, interval=args.interval)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_doctor(args, cfg: Config) -> int:
    from .doctor import run_doctor

    return run_doctor(cfg, Path(args.fonts_dir), offline=args.offline,
                      render=not args.no_render, ai=not args.no_ai)


def cmd_twitch_auth(args, cfg: Config) -> int:
    from .twitch import TwitchUserAuth

    cfg.require("twitch_client_id")
    auth = TwitchUserAuth(cfg.twitch_client_id, cfg.twitch_client_secret, cfg.twitch_token_path)
    device = auth.start_device_flow()
    print(f"Ouvre {device['verification_uri']} et valide le code : {device['user_code']}")
    auth.poll_device_flow(device)
    print(f"Token Twitch enregistré dans {cfg.twitch_token_path}")
    return 0


def cmd_tiktok_auth(args, cfg: Config) -> int:
    from .tiktok import TikTokClient, authorize_url

    cfg.require("tiktok_client_key", "tiktok_client_secret", "tiktok_redirect_uri")
    if not args.code:
        print("1. Ouvre cette URL et autorise l'application :\n")
        print(authorize_url(cfg.tiktok_client_key, cfg.tiktok_redirect_uri))
        print("\n2. Récupère le paramètre `code` dans l'URL de redirection, puis lance :")
        print("   clipbot tiktok-auth --code <CODE>")
        return 0
    client = TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret, cfg.tiktok_token_path)
    client.exchange_code(args.code, cfg.tiktok_redirect_uri)
    print(f"Token enregistré dans {cfg.tiktok_token_path}")
    print(client.creator_info())
    return 0


def cmd_youtube_auth(args, cfg: Config) -> int:
    from .youtube import YouTubeClient

    cfg.require("youtube_client_id", "youtube_client_secret")
    yt = YouTubeClient(cfg.youtube_client_id, cfg.youtube_client_secret, cfg.youtube_token_path)
    device = yt.start_device_flow()
    print(f"Ouvre {device['verification_url']} et valide le code : {device['user_code']}")
    yt.poll_device_flow(device)
    print(f"Token YouTube enregistré dans {cfg.youtube_token_path}")
    print(f"Chaîne : {yt.channel().get('title', '?')}")
    return 0


def cmd_instagram_auth(args, cfg: Config) -> int:
    from .instagram import InstagramClient

    token = args.token or cfg.instagram_access_token
    if not token:
        raise SystemExit("Passe le token longue durée : clipbot instagram-auth --token …")
    ig = InstagramClient(cfg.instagram_token_path, user_id=args.user_id or cfg.instagram_user_id,
                         host=cfg.instagram_graph_host)
    tok = ig.save(token, args.user_id or cfg.instagram_user_id)
    print(f"Token Instagram enregistré dans {cfg.instagram_token_path}")
    print(f"Compte : @{ig.account().get('username', '?')} (id {tok['user_id']})")
    return 0


def _add_render_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--layout", choices=["auto", "blur", "crop", "split"], default="auto",
                   help="auto = détection du visage ; blur = vidéo centrée sur fond flouté ; "
                        "crop = recadrage plein écran ; split = facecam en haut / jeu en bas")
    p.add_argument("--language", default=None, help="langue forcée pour Whisper (ex: fr)")
    p.add_argument("--no-subs", action="store_true", help="désactive les sous-titres")
    p.add_argument("--font", default="Montserrat Black")
    p.add_argument("--fonts-dir", default="fonts", help="dossier de polices .ttf pour libass")
    p.add_argument("--highlight", default="#FFE600", help="couleur du mot en cours")
    p.add_argument("--max-duration", type=float, default=60.0)


def _add_publish_opts(p: argparse.ArgumentParser, *, with_publish_flag: bool = True) -> None:
    from .pipeline import PLATFORMS

    p.add_argument("--platform", "-p", action="append", choices=PLATFORMS,
                   help="plateforme de publication, répétable (défaut : CLIPBOT_PLATFORMS)")
    if with_publish_flag:
        when = p.add_mutually_exclusive_group()
        when.add_argument("--publish", action="store_true",
                          help="publie tout de suite (sinon : à valider via `review`)")
        when.add_argument("--schedule", action="store_true",
                          help="programme sur le prochain créneau libre (CLIPBOT_POST_SLOTS)")
        p.add_argument("--caption",
                       default="{title} 🎮 @{channel_tag} sur Twitch #twitch #clip #fyp",
                       help="modèle de légende : {title} {channel} {channel_tag} {clipper}")
        p.add_argument("--ai-caption", action="store_true",
                       help="génère accroche + hashtags avec Claude")
    p.add_argument("--mode", choices=["draft", "direct"], default="draft",
                   help="TikTok : draft = boîte de réception, direct = publication")
    p.add_argument("--privacy", default="SELF_ONLY",
                   choices=["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR",
                            "PUBLIC_TO_EVERYONE"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clipbot", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="récupère et traite les clips existants les plus viraux")
    run.add_argument("--channel", "-c", action="append",
                     help="login Twitch, répétable (défaut : CLIPBOT_CHANNELS ; "
                          "sinon découverte automatique des temps forts)")
    run.add_argument("--discover-language", default="fr", metavar="LANG",
                     help="découverte auto : langue des streams scannés ('' = toutes)")
    run.add_argument("--streamers", type=int, default=30,
                     help="découverte auto : nb de lives les plus regardés scannés")
    run.add_argument("--hours", type=float, default=24, help="fenêtre de recherche des clips")
    run.add_argument("--top", type=int, default=3, help="nb de clips par chaîne et par run")
    run.add_argument("--min-views", type=int, default=50)
    run.add_argument("--every", type=float, default=0, metavar="MIN",
                     help="relance la recherche toutes les MIN minutes (mode serveur)")
    _add_publish_opts(run)
    _add_render_opts(run)
    run.set_defaults(func=cmd_run)

    watch = sub.add_parser("watch", help="surveille un live et clippe les pics de chat")
    watch.add_argument("channel", nargs="*",
                       help="login(s) Twitch (défaut : CLIPBOT_WATCH_CHANNELS)")
    watch.add_argument("--ratio", type=float, default=3.0,
                       help="activité du chat vs normale pour déclencher (défaut x3)")
    watch.add_argument("--min-rate", type=float, default=1.5,
                       help="score minimal par seconde (messages pondérés)")
    watch.add_argument("--cooldown", type=float, default=90.0,
                       help="secondes minimum entre deux clips")
    watch.add_argument("--forever", action="store_true",
                       help="après la fin du live, attend le suivant (mode serveur)")
    _add_publish_opts(watch)
    _add_render_opts(watch)
    watch.set_defaults(func=cmd_watch)

    render = sub.add_parser("render", help="convertit une vidéo locale en 9:16 sous-titré")
    render.add_argument("input")
    render.add_argument("-o", "--output")
    _add_render_opts(render)
    render.set_defaults(func=cmd_render)

    review = sub.add_parser(
        "app", aliases=["review", "serve"],
        help="interface web + pilote automatique + publication programmée (tout-en-un)")
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=8000)
    review.add_argument("--no-publisher", action="store_true",
                        help="ne publie pas les clips programmés (si `publisher` tourne à part)")
    review.add_argument("--fonts-dir", default="fonts")
    review.add_argument("--language", default=None,
                        help="langue forcée pour Whisper lors des recherches (ex: fr)")
    _add_publish_opts(review, with_publish_flag=False)
    review.set_defaults(func=cmd_review)

    pub = sub.add_parser("publisher", help="publie les clips programmés à l'heure prévue")
    pub.add_argument("--interval", type=float, default=60, help="secondes entre deux vérifications")
    pub.add_argument("--once", action="store_true", help="un seul passage (pour un cron)")
    _add_publish_opts(pub, with_publish_flag=False)
    pub.set_defaults(func=cmd_publisher)

    doc = sub.add_parser("doctor", help="vérifie l'installation, les clés et les connexions")
    doc.add_argument("--offline", action="store_true", help="sans appel aux API")
    doc.add_argument("--no-render", action="store_true", help="sans rendu vidéo de test")
    doc.add_argument("--no-ai", action="store_true", help="sans vérifier Claude")
    doc.add_argument("--fonts-dir", default="fonts")
    doc.set_defaults(func=cmd_doctor)

    tw = sub.add_parser("twitch-auth", help="connecte ton compte Twitch (nécessaire pour `watch`)")
    tw.set_defaults(func=cmd_twitch_auth)

    auth = sub.add_parser("tiktok-auth", help="connecte ton compte TikTok (OAuth)")
    auth.add_argument("--code")
    auth.set_defaults(func=cmd_tiktok_auth)

    yt = sub.add_parser("youtube-auth", help="connecte ta chaîne YouTube (code à valider)")
    yt.set_defaults(func=cmd_youtube_auth)

    ig = sub.add_parser("instagram-auth", help="enregistre le token Instagram longue durée")
    ig.add_argument("--token", help="token longue durée (tableau de bord Meta)")
    ig.add_argument("--user-id", help="id du compte Instagram pro (sinon détecté)")
    ig.set_defaults(func=cmd_instagram_auth)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args, Config())


if __name__ == "__main__":
    sys.exit(main())
