"""cliptv : clips Twitch viraux → format vertical sous-titré → TikTok."""

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
        mode=getattr(args, "mode", "draft"),
        privacy=getattr(args, "privacy", "SELF_ONLY"),
    )


def cmd_run(args, cfg: Config) -> int:
    from .pipeline import process_clip
    from .state import State
    from .twitch import TwitchClient, rank_clips

    cfg.require("twitch_client_id", "twitch_client_secret")
    cfg.ensure_dirs()
    opts = options_from_args(args)
    state = State(cfg.db_path)
    twitch = TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret)

    for channel in args.channel:
        log.info("== %s ==", channel)
        broadcaster_id = twitch.get_broadcaster_id(channel)
        clips = twitch.get_clips(broadcaster_id, since_hours=args.hours)
        ranked = [c for c in rank_clips(clips, min_views=args.min_views,
                                        max_duration=args.max_duration)
                  if not state.is_done(c.id)]
        log.info("%d clips trouvés, %d nouveaux éligibles", len(clips), len(ranked))
        for clip in ranked[: args.top]:
            log.info("→ %s (%d vues, %.0f vues/h) %s", clip.title, clip.view_count,
                     clip.virality(), clip.url)
            process_clip(clip, channel, cfg, state, opts)
    return 0


def cmd_watch(args, cfg: Config) -> int:
    from .live import SpikeDetector, message_weight, read_chat
    from .pipeline import process_clip
    from .state import State
    from .twitch import TwitchClient, TwitchUserAuth, create_clip, get_stream

    cfg.require("twitch_client_id", "twitch_client_secret")
    cfg.ensure_dirs()
    opts = options_from_args(args)
    state = State(cfg.db_path)
    twitch = TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret)
    auth = TwitchUserAuth(cfg.twitch_client_id, cfg.twitch_client_secret, cfg.twitch_token_path)
    auth.access_token()  # échoue tout de suite si `twitch-auth` n'a pas été fait
    channel = args.channel
    broadcaster_id = twitch.get_broadcaster_id(channel)

    while not get_stream(twitch, channel):
        log.info("%s est hors ligne, nouvelle vérification dans 2 min…", channel)
        time.sleep(120)

    detector = SpikeDetector(ratio=args.ratio, min_score=args.min_rate, cooldown=args.cooldown)
    last_live_check = time.time()
    log.info("Surveillance du chat de %s (seuil x%.1f)…", channel, args.ratio)
    for event in read_chat(channel):
        now = time.time()
        if event:
            detector.add(event[0], message_weight(event[2]))
        if now - last_live_check > 300:
            last_live_check = now
            if not get_stream(twitch, channel):
                log.info("Fin du live de %s.", channel)
                return 0
        intensity = detector.check(now)
        if intensity is None:
            continue
        recent, baseline = detector.rates(now)
        log.info("🔥 Pic de chat (%.1f/s vs %.1f/s, x%.1f) → création d'un clip", recent,
                 baseline, intensity)
        try:
            clip = create_clip(twitch, auth, broadcaster_id)
        except Exception:
            log.exception("Création du clip impossible")
            continue
        if not clip:
            log.warning("Clip pas encore disponible, ignoré")
            continue
        log.info("Clip créé : %s", clip.url)
        # traité dans la foulée (le chat continue d'être lu ensuite)
        process_clip(clip, channel, cfg, state, opts)
    return 0


def cmd_render(args, cfg: Config) -> int:
    from .pipeline import render_video

    src = Path(args.input)
    dst = Path(args.output) if args.output else src.with_name(src.stem + "_vertical.mp4")
    render_video(src, dst, cfg, options_from_args(args))
    print(dst)
    return 0


def cmd_review(args, cfg: Config) -> int:
    from .review import make_server

    opts = Options(mode=args.mode, privacy=args.privacy)
    server = make_server(cfg, opts, host=args.host, port=args.port)
    print(f"Interface de revue : http://{args.host}:{args.port}  (Ctrl+C pour quitter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


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
    if with_publish_flag:
        p.add_argument("--publish", action="store_true",
                       help="publie directement sur TikTok (sinon : à valider via `review`)")
        p.add_argument("--caption",
                       default="{title} 🎮 @{channel_tag} sur Twitch #twitch #clip #fyp",
                       help="modèle de légende : {title} {channel} {channel_tag} {clipper}")
        p.add_argument("--ai-caption", action="store_true",
                       help="génère accroche + hashtags avec Claude")
    p.add_argument("--mode", choices=["draft", "direct"], default="draft")
    p.add_argument("--privacy", default="SELF_ONLY",
                   choices=["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR",
                            "PUBLIC_TO_EVERYONE"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clipbot", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="récupère et traite les clips existants les plus viraux")
    run.add_argument("--channel", "-c", action="append", required=True,
                     help="login Twitch (répétable)")
    run.add_argument("--hours", type=float, default=24, help="fenêtre de recherche des clips")
    run.add_argument("--top", type=int, default=3, help="nb de clips par chaîne et par run")
    run.add_argument("--min-views", type=int, default=50)
    _add_publish_opts(run)
    _add_render_opts(run)
    run.set_defaults(func=cmd_run)

    watch = sub.add_parser("watch", help="surveille un live et clippe les pics de chat")
    watch.add_argument("channel", help="login Twitch")
    watch.add_argument("--ratio", type=float, default=3.0,
                       help="activité du chat vs normale pour déclencher (défaut x3)")
    watch.add_argument("--min-rate", type=float, default=1.5,
                       help="score minimal par seconde (messages pondérés)")
    watch.add_argument("--cooldown", type=float, default=90.0,
                       help="secondes minimum entre deux clips")
    _add_publish_opts(watch)
    _add_render_opts(watch)
    watch.set_defaults(func=cmd_watch)

    render = sub.add_parser("render", help="convertit une vidéo locale en 9:16 sous-titré")
    render.add_argument("input")
    render.add_argument("-o", "--output")
    _add_render_opts(render)
    render.set_defaults(func=cmd_render)

    review = sub.add_parser("review", help="interface web pour valider/publier les clips")
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=8000)
    _add_publish_opts(review, with_publish_flag=False)
    review.set_defaults(func=cmd_review)

    tw = sub.add_parser("twitch-auth", help="connecte ton compte Twitch (nécessaire pour `watch`)")
    tw.set_defaults(func=cmd_twitch_auth)

    auth = sub.add_parser("tiktok-auth", help="connecte ton compte TikTok (OAuth)")
    auth.add_argument("--code")
    auth.set_defaults(func=cmd_tiktok_auth)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args, Config())


if __name__ == "__main__":
    sys.exit(main())
