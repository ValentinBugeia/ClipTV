"""Traitement complet d'un clip : téléchargement → cadrage → sous-titres → légende → rendu
→ publication (TikTok, YouTube Shorts, Instagram Reels), immédiate ou programmée."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .state import State

log = logging.getLogger("clipbot")

# un seul rendu à la fois (Whisper + ffmpeg) : le pilote auto, les lives et les recherches
# lancées depuis le navigateur peuvent tourner en même temps sur un petit serveur
_render_lock = threading.Lock()


@dataclass
class Options:
    layout: str = "auto"            # auto | blur | crop | split
    language: str | None = None
    subtitles: bool = True
    font: str = "Montserrat Black"
    fonts_dir: Path | None = None
    highlight: str = "#FFE600"
    max_duration: float = 60.0
    caption_template: str = "{title} 🎮 @{channel_tag} sur Twitch #twitch #clip #fyp"
    ai_caption: bool = False
    publish: bool = False           # publie tout de suite après le rendu
    schedule: bool = False          # programme sur le prochain créneau libre
    platforms: list[str] = field(default_factory=list)  # vide = cfg.platforms
    mode: str = "draft"             # TikTok : draft | direct
    privacy: str = "SELF_ONLY"      # TikTok, publication directe


def template_caption(template: str, clip) -> str:
    return template.format(
        title=clip.title,
        channel=clip.broadcaster_name,
        channel_tag=clip.broadcaster_name.lower().replace(" ", ""),
        clipper=clip.creator_name,
    )


def render_video(src: Path, dst: Path, cfg: Config, opts: Options) -> tuple[Path, list]:
    """Rend la vidéo verticale. Retourne (chemin, mots transcrits)."""
    from .render import render_vertical
    from .subtitles import transcribe, write_ass

    layout, cam_box, crop_center, crop_track = opts.layout, None, None, None
    if layout in ("auto", "crop"):
        from .facecam import (CAMERA_MIN_HEIGHT, cam_crop_box, choose_layout, detect_face,
                              smooth_track)

        face = detect_face(src)
        if layout == "auto":
            layout = choose_layout(face)
        if face and layout == "split":
            cam_box = cam_crop_box(face)
        elif face and layout == "crop" and face.relative_height >= CAMERA_MIN_HEIGHT:
            # caméra en grand : le zoom suit le visage (sinon : centre de l'image)
            crop_center = face.cx / face.frame_w
            crop_track = smooth_track(face.track) or None
        log.info("Cadrage : %s%s%s", layout, f" (visage {face.w}x{face.h})" if face else "",
                 " avec suivi du visage" if crop_track and len(crop_track) > 1 else "")

    words, subs = [], None
    if opts.subtitles:
        log.info("Transcription de %s (whisper %s)…", src.name, cfg.whisper_model)
        words = transcribe(src, model_size=cfg.whisper_model, device=cfg.whisper_device,
                           language=opts.language)
        if words:
            # en split, la jonction facecam/jeu est vers 40 % de la hauteur : on descend un peu
            subs = write_ass(words, dst.with_suffix(".ass"), font=opts.font,
                             highlight=opts.highlight,
                             margin_v=420 if layout == "split" else 560)
        else:
            log.info("Aucune parole détectée, pas de sous-titres.")
    log.info("Rendu vertical (%s) → %s", layout, dst)
    render_vertical(src, dst, layout=layout, subtitles=subs, max_duration=opts.max_duration,
                    fonts_dir=opts.fonts_dir, cam_box=cam_box, crop_center=crop_center,
                    crop_track=crop_track)
    return dst, words


def make_caption(clip, words: list, cfg: Config, opts: Options) -> str:
    if opts.ai_caption:
        from .captions import generate_caption

        caption = generate_caption(
            title=clip.title,
            channel=clip.broadcaster_name,
            transcript=" ".join(w.text for w in words),
            model=cfg.llm_model,
        )
        if caption:
            return caption
    return template_caption(opts.caption_template, clip)


PLATFORMS = ("tiktok", "youtube", "instagram")


def publish_to(platform: str, path: Path, caption: str, cfg: Config, opts: Options) -> str:
    """Publie une vidéo sur une plateforme. Retourne l'identifiant du post."""
    if platform == "tiktok":
        from .tiktok import TikTokClient

        cfg.require("tiktok_client_key", "tiktok_client_secret")
        tiktok = TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret,
                              cfg.tiktok_token_path)
        publish_id = tiktok.publish(path, caption=caption, mode=opts.mode,
                                    privacy_level=opts.privacy)
        result = tiktok.wait(publish_id)
        log.info("TikTok : %s", result.get("status"))
        if result.get("status") == "FAILED":
            raise RuntimeError(result.get("fail_reason", "publication échouée"))
        return publish_id
    if platform == "youtube":
        from .youtube import YouTubeClient

        cfg.require("youtube_client_id", "youtube_client_secret")
        yt = YouTubeClient(cfg.youtube_client_id, cfg.youtube_client_secret,
                           cfg.youtube_token_path)
        video_id = yt.upload(path, caption=caption, privacy=cfg.youtube_privacy)
        log.info("YouTube : https://youtube.com/shorts/%s (%s)", video_id, cfg.youtube_privacy)
        return video_id
    if platform == "instagram":
        from .instagram import InstagramClient

        ig = InstagramClient(cfg.instagram_token_path, user_id=cfg.instagram_user_id,
                             access_token=cfg.instagram_access_token,
                             host=cfg.instagram_graph_host)
        media_id = ig.publish_reel(path, caption=caption)
        log.info("Instagram : Reel publié (%s)", media_id)
        return media_id
    raise ValueError(f"Plateforme inconnue : {platform} (choix : {', '.join(PLATFORMS)})")


def publish_clip(clip_id: str, cfg: Config, state: State, opts: Options) -> list[str]:
    """Publie un clip déjà réservé (``state.claim``) sur toutes les plateformes.

    Les plateformes déjà réussies lors d'une tentative précédente sont sautées.
    Retourne la liste des erreurs (vide si tout est publié).
    """
    clip = state.get(clip_id)
    path, caption = Path(clip["output_path"]), clip["caption"] or ""
    done = state.posts(clip_id)
    errors, tiktok_id = [], None
    for platform in opts.platforms or cfg.platforms:
        if done.get(platform, {}).get("status") == "ok":
            continue
        try:
            post_id = publish_to(platform, path, caption, cfg, opts)
        except (Exception, SystemExit) as exc:  # SystemExit : config/token manquant
            log.exception("Publication %s échouée pour %s", platform, clip_id)
            state.record_post(clip_id, platform, "failed", error=str(exc))
            errors.append(f"{platform} : {exc}")
            continue
        state.record_post(clip_id, platform, "ok", post_id=post_id)
        if platform == "tiktok":
            tiktok_id = post_id
    status = "failed" if errors else "published"
    state.record(clip_id, clip["channel"], status, publish_id=tiktok_id,
                 error=" | ".join(errors) or None)
    return errors


def process_clip(clip, channel: str, cfg: Config, state: State, opts: Options) -> bool:
    """Traite un clip de bout en bout. Retourne True si tout s'est bien passé."""
    from .download import download_clip

    meta = dict(title=clip.title, url=clip.url, view_count=clip.view_count)
    try:
        src = download_clip(clip.url, cfg.downloads_dir, clip.id)
        dst = cfg.output_dir / f"{channel}_{clip.id}.mp4"
        with _render_lock:
            _, words = render_video(src, dst, cfg, opts)
        caption = make_caption(clip, words, cfg, opts)
        state.record(clip.id, channel, "rendered", output_path=str(dst), caption=caption, **meta)
    except Exception as exc:  # on continue avec les autres clips
        log.exception("Échec pour %s", clip.id)
        state.record(clip.id, channel, "failed", error=str(exc), **meta)
        return False
    if opts.publish:
        state.claim(clip.id)
        return not publish_clip(clip.id, cfg, state, opts)
    if opts.schedule:
        from .schedule import format_when, schedule_clip

        when = schedule_clip(state, cfg, clip.id)
        log.info("Programmé pour %s", format_when(int(when.timestamp()), cfg.timezone))
    return True


def run_channels(channels: list[str], cfg: Config, state: State, opts: Options, twitch, *,
                 hours: float = 24, top: int = 3, min_views: int = 50) -> list[tuple[str, bool]]:
    """Traite les clips les plus viraux de chaque chaîne. Retourne [(clip_id, succès)]."""
    from .twitch import rank_clips

    results = []
    for channel in channels:
        log.info("== %s ==", channel)
        broadcaster_id = twitch.get_broadcaster_id(channel)
        clips = twitch.get_clips(broadcaster_id, since_hours=hours)
        ranked = [c for c in rank_clips(clips, min_views=min_views,
                                        max_duration=opts.max_duration)
                  if not state.is_done(c.id)]
        log.info("%d clips trouvés, %d nouveaux éligibles", len(clips), len(ranked))
        for clip in ranked[:top]:
            log.info("→ %s (%d vues, %.0f vues/h) %s", clip.title, clip.view_count,
                     clip.virality(), clip.url)
            try:
                ok = process_clip(clip, channel, cfg, state, opts)
            except Exception:  # erreur réseau Twitch etc. : on passe à la suite
                log.exception("Erreur sur %s", clip.id)
                ok = False
            results.append((clip.id, ok))
    return results
