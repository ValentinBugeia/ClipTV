"""Traitement complet d'un clip : téléchargement → cadrage → sous-titres → légende → rendu
→ publication (TikTok, YouTube Shorts, Instagram Reels), immédiate ou programmée."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import progress
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
    caption_template: str = "{title}\n🎮 twitch.tv/{channel_tag}"
    ai_caption: bool = False
    publish: bool = False           # publie tout de suite après le rendu
    schedule: bool = False          # programme sur le prochain créneau libre
    platforms: list[str] = field(default_factory=list)  # vide = cfg.platforms
    mode: str = "draft"             # TikTok : draft | direct
    privacy: str = "SELF_ONLY"      # TikTok, publication directe
    tiktok_options: dict = field(default_factory=dict)  # réglages choisis pour ce clip
    hook_title: bool = True         # titre d'accroche en haut pendant les 3 premières secondes
    trim_start: bool = True         # coupe le début mou (silence, attente)
    normalize_audio: bool = True    # volume égalisé (-14 LUFS)
    skip_burned_subs: bool = True   # pas de sous-titres en double si le stream en a déjà


def template_caption(template: str, clip) -> str:
    """Légende sans IA. Le modèle par défaut est complété par les hashtags du clip
    (streamer, jeu, niche) ; un modèle personnalisé avec ses propres # est laissé tel quel."""
    text = template.format(
        title=clip.title,
        channel=clip.broadcaster_name,
        channel_tag=clip.broadcaster_name.lower().replace(" ", ""),
        clipper=clip.creator_name,
    )
    if "#" in template:
        return text
    from .captions import base_hashtags, merge_hashtags

    tags = merge_hashtags(base_hashtags(clip.broadcaster_name, getattr(clip, "category", "")))
    return f"{text}\n{' '.join(tags)}"


def whisper_language(code: str | None) -> str | None:
    """Langue Twitch (« fr », « en », « zh-hant »…) → code Whisper, si Whisper la connaît.

    Donner la langue à Whisper lui évite une passe de détection (≈ 15 % du temps de
    transcription) ; les clips viennent de streams filtrés par langue.
    """
    base = (code or "").lower().split("-")[0]
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES
    except ImportError:
        return None
    return base if base in _LANGUAGE_CODES else None


def render_video(src: Path, dst: Path, cfg: Config, opts: Options, *,
                 allow_split: bool = True, language: str | None = None, on_words=None,
                 title: str = "") -> tuple[Path, list]:
    """Rend la vidéo verticale. Retourne (chemin, mots transcrits).

    ``allow_split=False`` (catégories IRL, Just Chatting…) : jamais de découpage
    facecam / jeu, même si un visage est détecté dans la scène.

    La détection du visage tourne en parallèle de la transcription ; ``on_words(words)``
    est appelé dès la transcription finie (la légende peut s'écrire pendant le montage).
    """
    from concurrent.futures import ThreadPoolExecutor

    from .render import render_vertical
    from .subtitles import transcribe, write_ass

    layout, cam_box, crop_center, crop_track = opts.layout, None, None, None
    cam_height = None
    pool = ThreadPoolExecutor(max_workers=2)
    face_job = burned_job = None
    if layout in ("auto", "crop"):
        from .facecam import detect_face

        progress.step("face")
        face_job = pool.submit(detect_face, src)
    if opts.subtitles and opts.skip_burned_subs:
        from .enhance import has_burned_subtitles

        burned_job = pool.submit(has_burned_subtitles, src)

    words = []
    try:
        if opts.subtitles:
            log.info("Transcription de %s (whisper %s)…", src.name, cfg.whisper_model)
            progress.step("transcribe", "en parallèle de la détection du visage"
                          if face_job else "")
            words = transcribe(src, model_size=cfg.whisper_model, device=cfg.whisper_device,
                               language=opts.language or language)
        face = face_job.result() if face_job else None
        burned = bool(burned_job.result()) if burned_job else False
    finally:
        pool.shutdown(wait=True)
    if on_words is not None:
        on_words(words)

    if face_job is not None:
        from .facecam import (CAMERA_MIN_HEIGHT, cam_crop_box, cam_zone_height, choose_layout,
                              smooth_track)

        if layout == "auto":
            layout = choose_layout(face, allow_split=allow_split)
        if face and layout == "split":
            cam_height = cam_zone_height(face)  # taille adaptée à la facecam d'origine
            cam_box = cam_crop_box(face, zone_h=cam_height)
        elif face and layout == "crop" and face.relative_height >= CAMERA_MIN_HEIGHT:
            # caméra en grand : le zoom suit le visage (sinon : centre de l'image)
            crop_center = face.cx / face.frame_w
            crop_track = smooth_track(face.track) or None
        log.info("Cadrage : %s%s%s", layout, f" (visage {face.w}x{face.h})" if face else "",
                 " avec suivi du visage" if crop_track and len(crop_track) > 1 else "")

    from .enhance import find_start, hook_text
    from .subtitles import SAMPLE_RATE, Word, load_audio

    start = 0.0
    if opts.trim_start:
        try:
            start = find_start(load_audio(src), SAMPLE_RATE, words)
        except Exception:
            log.warning("Analyse du début impossible : clip gardé en entier", exc_info=True)
        if start:
            log.info("Début coupé : %.1f s de mise en route retirées", start)
    shown = [Word(w.text, w.start - start, w.end - start) for w in words if w.end > start]
    if burned:
        log.info("Sous-titres déjà présents dans le stream : pas de sous-titres ajoutés.")
        shown = []
    hook = hook_text(title) if opts.hook_title else ""

    subs = None
    if (opts.subtitles and shown) or hook:
        if opts.subtitles and not shown and not burned:
            log.info("Aucune parole détectée, pas de sous-titres.")
        # en split, la jonction facecam/jeu est vers 40 % de la hauteur : on descend un peu ;
        # l'accroche se place en haut de l'image, ou en haut du jeu (sous la facecam)
        subs = write_ass(shown if opts.subtitles else [], dst.with_suffix(".ass"),
                         font=opts.font, highlight=opts.highlight,
                         margin_v=420 if layout == "split" else 560, hook=hook,
                         hook_margin=((cam_height or 768) + 40) if layout == "split" else 260)
    elif opts.subtitles:
        log.info("Aucune parole détectée, pas de sous-titres.")
    log.info("Rendu vertical (%s) → %s", layout, dst)
    progress.step("render", {"split": "facecam en haut, jeu en bas", "crop": "zoom plein écran",
                             "blur": "fond flouté"}.get(layout, layout))
    render_vertical(src, dst, layout=layout, subtitles=subs, max_duration=opts.max_duration,
                    fonts_dir=opts.fonts_dir, cam_box=cam_box, crop_center=crop_center,
                    crop_track=crop_track, cam_height=cam_height, start=start,
                    normalize_audio=opts.normalize_audio)
    return dst, words


def make_caption(clip, words: list, cfg: Config, opts: Options) -> str:
    if opts.ai_caption:
        from .captions import generate_caption

        caption = generate_caption(
            title=clip.title,
            channel=clip.broadcaster_name,
            transcript=" ".join(w.text for w in words),
            model=cfg.llm_model,
            category=getattr(clip, "category", ""),
        )
        if caption:
            return caption
    return template_caption(opts.caption_template, clip)


PLATFORMS = ("tiktok", "youtube", "instagram")
PLATFORM_LABELS = {"tiktok": "TikTok", "youtube": "YouTube", "instagram": "Instagram"}


def publish_to(platform: str, path: Path, caption: str, cfg: Config, opts: Options) -> str:
    """Publie une vidéo sur une plateforme. Retourne l'identifiant du post."""
    if platform == "tiktok":
        from .tiktok import TikTokClient

        cfg.require("tiktok_client_key", "tiktok_client_secret")
        tiktok = TikTokClient(cfg.tiktok_client_key, cfg.tiktok_client_secret,
                              cfg.tiktok_token_path)
        publish_id = tiktok.publish(path, caption=caption, mode=opts.mode,
                                    privacy_level=opts.privacy,
                                    post_info=opts.tiktok_options or None)
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


TIKTOK_MODE = "tiktok_mode"  # réglage de l'interface : draft | direct


def tiktok_mode(state: State, opts: Options) -> str:
    """Mode d'envoi TikTok : réglage de la page Comptes, sinon option de lancement.

    - ``draft`` : brouillon dans l'app TikTok du téléphone ;
    - ``direct`` : publiée en privé sur le profil (tant que l'app n'est pas validée),
      visible et modifiable depuis tiktok.com sur PC.
    """
    mode = state.get_settings().get(TIKTOK_MODE)
    return mode if mode in ("draft", "direct") else opts.mode


def publish_clip(clip_id: str, cfg: Config, state: State, opts: Options) -> list[str]:
    """Publie un clip déjà réservé (``state.claim``) sur toutes les plateformes.

    Les plateformes déjà réussies lors d'une tentative précédente sont sautées.
    Retourne la liste des erreurs (vide si tout est publié).
    """
    from dataclasses import replace

    from .tiktok_post import SETTING as POST_OPTIONS

    chosen = state.get_settings().get(POST_OPTIONS, {}).get(clip_id) or {}
    opts = replace(opts, mode=tiktok_mode(state, opts), tiktok_options=chosen)
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
            from .errors import explain

            state.record_post(clip_id, platform, "failed", error=explain(exc))
            errors.append(f"{PLATFORM_LABELS.get(platform, platform)} : {explain(exc)}")
            continue
        state.record_post(clip_id, platform, "ok", post_id=post_id)
        if platform == "tiktok":
            tiktok_id = post_id
    status = "failed" if errors else "published"
    state.record(clip_id, clip["channel"], status, publish_id=tiktok_id,
                 error=" | ".join(errors) or None)
    return errors


def process_clip(clip, channel: str, cfg: Config, state: State, opts: Options,
                 source=None) -> bool:
    """Traite un clip de bout en bout. Retourne True si tout s'est bien passé.

    ``source`` : fonction qui renvoie la vidéo déjà téléchargée (téléchargement anticipé).
    Lève ``progress.Cancelled`` si l'utilisateur arrête la recherche.
    """
    from .download import download_clip

    from .twitch import is_non_gaming

    category = getattr(clip, "category", "")
    meta = dict(title=clip.title, url=clip.url, view_count=clip.view_count, category=category)
    try:
        progress.step("download", f"{channel} · {clip.title}")
        src = source() if source else download_clip(clip.url, cfg.downloads_dir, clip.id)
        dst = cfg.output_dir / f"{channel}_{clip.id}.mp4"
        if category:
            log.info("Catégorie : %s", category)
        caption_job: dict = {}

        def write_caption(words):  # pendant le montage vidéo (réseau, pas de CPU)
            def run():
                try:
                    caption_job["text"] = make_caption(clip, words, cfg, opts)
                except Exception:
                    log.exception("Légende IA impossible : légende modèle utilisée")
            caption_job["thread"] = threading.Thread(target=run, daemon=True)
            caption_job["thread"].start()

        with _render_lock:
            render_video(src, dst, cfg, opts, allow_split=not is_non_gaming(category),
                         language=whisper_language(getattr(clip, "language", "")),
                         title=clip.title,
                         on_words=write_caption)
        progress.step("caption")
        if "thread" in caption_job:
            caption_job["thread"].join()
        caption = caption_job.get("text") or template_caption(opts.caption_template, clip)
        state.record(clip.id, channel, "rendered", output_path=str(dst), caption=caption, **meta)
    except progress.Cancelled:
        log.info("Recherche arrêtée pendant %s", clip.id)
        raise
    except Exception as exc:  # on continue avec les autres clips
        log.exception("Échec pour %s", clip.id)
        from .errors import explain

        state.record(clip.id, channel, "failed", error=explain(exc), **meta)
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
        progress.step("search", f"Clips de {channel}")
        broadcaster_id = twitch.get_broadcaster_id(channel)
        clips = twitch.get_clips(broadcaster_id, since_hours=hours)
        ranked = [c for c in rank_clips(clips, min_views=min_views,
                                        max_duration=opts.max_duration)
                  if not state.is_done(c.id)]
        log.info("%d clips trouvés, %d nouveaux éligibles", len(clips), len(ranked))
        twitch.annotate_categories(ranked[:top])
        prefetch = Prefetcher(cfg, ranked[:top])
        try:
            for i, clip in enumerate(ranked[:top], 1):
                progress.clip(i, min(top, len(ranked)), clip.title)
                log.info("→ %s (%d vues, %.0f vues/h) %s", clip.title, clip.view_count,
                         clip.virality(), clip.url)
                results.append((clip.id, _process(clip, channel, cfg, state, opts, prefetch)))
        finally:
            prefetch.close()
    return results


def _process(clip, channel, cfg, state, opts, prefetch) -> bool:
    try:
        return process_clip(clip, channel, cfg, state, opts, source=prefetch.source(clip))
    except Exception:  # erreur réseau Twitch etc. : on passe à la suite
        log.exception("Erreur sur %s", clip.id)
        return False


class Prefetcher:
    """Télécharge les clips suivants pendant que le clip courant est monté."""

    def __init__(self, cfg: Config, clips, workers: int = 3):
        from concurrent.futures import ThreadPoolExecutor

        from .download import download_clip

        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.jobs = {c.id: self.pool.submit(download_clip, c.url, cfg.downloads_dir, c.id)
                     for c in clips}

    def source(self, clip):
        job = self.jobs.get(clip.id)
        return job.result if job else None

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)

