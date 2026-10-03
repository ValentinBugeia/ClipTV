"""Traitement complet d'un clip : téléchargement → cadrage → sous-titres → légende → rendu → TikTok."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .state import State

log = logging.getLogger("clipbot")


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
    publish: bool = False
    mode: str = "draft"             # draft | direct
    privacy: str = "SELF_ONLY"


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

    layout, cam_box, crop_center = opts.layout, None, None
    if layout == "auto":
        from .facecam import cam_crop_box, choose_layout, detect_face

        face = detect_face(src)
        layout = choose_layout(face)
        if face and layout == "split":
            cam_box = cam_crop_box(face)
        elif face and layout == "crop":
            crop_center = face.cx / face.frame_w
        log.info("Cadrage auto : %s%s", layout, f" (visage {face.w}x{face.h})" if face else "")

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
                    fonts_dir=opts.fonts_dir, cam_box=cam_box, crop_center=crop_center)
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


def publish(path: Path, caption: str, cfg: Config, opts: Options) -> str:
    from .tiktok import TikTokClient

    cfg.require("tiktok_client_key", "tiktok_client_secret")
    tiktok = TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret, cfg.tiktok_token_path)
    publish_id = tiktok.publish(path, caption=caption, mode=opts.mode, privacy_level=opts.privacy)
    result = tiktok.wait(publish_id)
    log.info("TikTok : %s", result.get("status"))
    if result.get("status") == "FAILED":
        raise RuntimeError(result.get("fail_reason", "publication échouée"))
    return publish_id


def process_clip(clip, channel: str, cfg: Config, state: State, opts: Options) -> bool:
    """Traite un clip de bout en bout. Retourne True si tout s'est bien passé."""
    from .download import download_clip

    meta = dict(title=clip.title, url=clip.url, view_count=clip.view_count)
    try:
        src = download_clip(clip.url, cfg.downloads_dir, clip.id)
        dst = cfg.output_dir / f"{channel}_{clip.id}.mp4"
        _, words = render_video(src, dst, cfg, opts)
        caption = make_caption(clip, words, cfg, opts)
        state.record(clip.id, channel, "rendered", output_path=str(dst), caption=caption, **meta)
        if opts.publish:
            publish_id = publish(dst, caption, cfg, opts)
            state.record(clip.id, channel, "published", publish_id=publish_id, **meta)
        return True
    except Exception as exc:  # on continue avec les autres clips
        log.exception("Échec pour %s", clip.id)
        state.record(clip.id, channel, "failed", error=str(exc), **meta)
        return False
