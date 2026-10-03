"""Point d'entrée en ligne de commande : `clipbot ...`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Config

log = logging.getLogger("clipbot")


def make_caption(template: str, clip) -> str:
    return template.format(
        title=clip.title,
        channel=clip.broadcaster_name,
        channel_tag=clip.broadcaster_name.lower().replace(" ", ""),
        clipper=clip.creator_name,
    )


def process_video(src: Path, dst: Path, cfg: Config, args) -> Path:
    from .render import render_vertical
    from .subtitles import transcribe, write_ass

    subs = None
    if not args.no_subs:
        log.info("Transcription de %s (whisper %s)…", src.name, cfg.whisper_model)
        words = transcribe(src, model_size=cfg.whisper_model, device=cfg.whisper_device,
                           language=args.language)
        if words:
            subs = write_ass(words, dst.with_suffix(".ass"), font=args.font,
                             highlight=args.highlight)
        else:
            log.info("Aucune parole détectée, pas de sous-titres.")
    log.info("Rendu vertical (%s) → %s", args.layout, dst)
    fonts_dir = Path(args.fonts_dir) if args.fonts_dir else None
    return render_vertical(src, dst, layout=args.layout, subtitles=subs,
                           max_duration=args.max_duration, fonts_dir=fonts_dir)


def cmd_run(args, cfg: Config) -> int:
    from .download import download_clip
    from .state import State
    from .twitch import TwitchClient, rank_clips

    cfg.require("twitch_client_id", "twitch_client_secret")
    cfg.ensure_dirs()
    state = State(cfg.db_path)
    twitch = TwitchClient(cfg.twitch_client_id, cfg.twitch_client_secret)

    tiktok = None
    if args.publish:
        from .tiktok import TikTokClient

        cfg.require("tiktok_client_key", "tiktok_client_secret")
        tiktok = TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret,
                              cfg.tiktok_token_path)

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
            meta = dict(title=clip.title, url=clip.url, view_count=clip.view_count)
            try:
                src = download_clip(clip.url, cfg.downloads_dir, clip.id)
                dst = cfg.output_dir / f"{channel}_{clip.id}.mp4"
                process_video(src, dst, cfg, args)
                state.record(clip.id, channel, "rendered", output_path=str(dst), **meta)

                if tiktok:
                    caption = make_caption(args.caption, clip)
                    publish_id = tiktok.publish(dst, caption=caption, mode=args.mode,
                                                privacy_level=args.privacy)
                    result = tiktok.wait(publish_id)
                    log.info("TikTok : %s", result.get("status"))
                    if result.get("status") == "FAILED":
                        raise RuntimeError(result.get("fail_reason", "publication échouée"))
                    state.record(clip.id, channel, "published", publish_id=publish_id, **meta)
            except Exception as exc:  # on continue avec les autres clips
                log.exception("Échec pour %s", clip.id)
                state.record(clip.id, channel, "failed", error=str(exc), **meta)
    return 0


def cmd_render(args, cfg: Config) -> int:
    src = Path(args.input)
    dst = Path(args.output) if args.output else src.with_name(src.stem + "_vertical.mp4")
    process_video(src, dst, cfg, args)
    print(dst)
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
    p.add_argument("--layout", choices=["blur", "crop", "split"], default="blur",
                   help="blur = vidéo centrée sur fond flouté, crop = recadrage centre, "
                        "split = facecam en haut / jeu en bas")
    p.add_argument("--language", default=None, help="langue forcée pour Whisper (ex: fr)")
    p.add_argument("--no-subs", action="store_true", help="désactive les sous-titres")
    p.add_argument("--font", default="Montserrat Black")
    p.add_argument("--fonts-dir", default="fonts", help="dossier de polices .ttf pour libass")
    p.add_argument("--highlight", default="#FFE600", help="couleur du mot en cours")
    p.add_argument("--max-duration", type=float, default=60.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clipbot", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="récupère, convertit et publie les meilleurs clips")
    run.add_argument("--channel", "-c", action="append", required=True,
                     help="login Twitch (répétable)")
    run.add_argument("--hours", type=float, default=24, help="fenêtre de recherche des clips")
    run.add_argument("--top", type=int, default=3, help="nb de clips par chaîne et par run")
    run.add_argument("--min-views", type=int, default=50)
    run.add_argument("--publish", action="store_true", help="publie sur TikTok")
    run.add_argument("--mode", choices=["draft", "direct"], default="draft")
    run.add_argument("--privacy", default="SELF_ONLY",
                     choices=["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR",
                              "PUBLIC_TO_EVERYONE"])
    run.add_argument("--caption", default="{title} 🎮 @{channel_tag} sur Twitch #twitch #clip #fyp")
    _add_render_opts(run)
    run.set_defaults(func=cmd_run)

    render = sub.add_parser("render", help="convertit une vidéo locale en 9:16 sous-titré")
    render.add_argument("input")
    render.add_argument("-o", "--output")
    _add_render_opts(render)
    render.set_defaults(func=cmd_render)

    auth = sub.add_parser("tiktok-auth", help="connecte ton compte TikTok (OAuth)")
    auth.add_argument("--code")
    auth.set_defaults(func=cmd_tiktok_auth)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if getattr(args, "fonts_dir", None) and not Path(args.fonts_dir).is_dir():
        args.fonts_dir = None
    return args.func(args, Config())


if __name__ == "__main__":
    sys.exit(main())
