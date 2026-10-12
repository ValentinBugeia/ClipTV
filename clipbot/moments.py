"""Moments : ClipTV ne monte plus le clip Twitch tel quel, il s'en sert pour repérer un
moment fort dans la rediffusion, puis découpe lui-même un clip complet.

Un clip Twitch, c'est un viewer qui appuie sur « Clip » : il démarre souvent au milieu de
la situation et s'arrête avant la réaction. Pour chaque moment :

1. plusieurs clips du même moment (même rediffusion, mêmes secondes) n'en font qu'un ;
2. on télécharge un **extrait léger** de la rediffusion autour du clip (15 s avant, 12 s
   après, en 160p : quelques Mo) — ou le clip lui-même si la rediffusion n'existe plus ;
3. on transcrit l'extrait (phrases avec leur temps) ;
4. le Radar (Claude) lit les phrases, regarde les images, et choisit le début et la fin :
   début de la situation → chute → fin de la réaction, jamais au milieu d'une phrase.
   Sans Claude, ``auto_cut`` fait de même avec les pauses entre les phrases et le son ;
5. pour les clips retenus seulement, la version 1080p de ce passage est téléchargée et
   recalée sur l'extrait par le son (les repères de Twitch ne sont pas précis à la
   seconde).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("clipbot.moments")

BEFORE = 15.0      # secondes de rediffusion prises avant le clip (la situation)
AFTER = 12.0       # et après (la fin de la réaction)
PAD = 4.0          # marge du téléchargement 1080p (les coupes tombent sur des images clés)
PHRASE_GAP = 0.6   # silence qui sépare deux phrases
MIN_LEN, MAX_LEN = 10.0, 60.0
WINDOW_FORMAT = "160p/160p30/worst[height>=144]/worst"
FINAL_FORMAT = "best[height<=1080][ext=mp4]/best[height<=1080]/best"


@dataclass
class Window:
    """Extrait léger autour du moment. ``vod_start`` : seconde de la rediffusion où il
    commence (None : c'est le clip Twitch lui-même) ; ``span`` : où se trouve le clip
    Twitch d'origine dans l'extrait."""
    path: Path
    vod_start: float | None
    length: float
    span: tuple[float, float]


def has_vod(clip) -> bool:
    return bool(getattr(clip, "video_id", "")) and getattr(clip, "vod_offset", None) is not None


# --- 1. un moment = plusieurs clips --------------------------------------------------------

def same_moment(a, b, tolerance: float = 3.0) -> bool:
    if not (has_vod(a) and has_vod(b)) or a.video_id != b.video_id:
        return False
    return (a.vod_offset < b.vod_offset + b.duration + tolerance and
            b.vod_offset < a.vod_offset + a.duration + tolerance)


def merge_moments(found: list) -> list:
    """[(clip, login)] → un seul clip par moment (le mieux classé) ; ``clip.clippers`` =
    nombre de viewers qui ont clippé ce moment (signe d'un vrai moment fort)."""
    kept: list = []
    for clip, login in found:
        twin = next((k for k, _ in kept if same_moment(k, clip)), None)
        if twin is None:
            clip.clippers = 1
            kept.append((clip, login))
        else:
            twin.clippers = getattr(twin, "clippers", 1) + 1
            log.info("Même moment que « %s » : %s", twin.title, clip.title)
    return kept


# --- 2. extrait léger ------------------------------------------------------------------------

def _vod_range(video_id: str, start: float, end: float, target: Path, fmt: str) -> Path:
    import yt_dlp
    from yt_dlp.utils import download_range_func

    from . import progress

    target.unlink(missing_ok=True)
    opts = {"outtmpl": str(target), "format": fmt, "quiet": True, "no_warnings": True,
            "download_ranges": download_range_func(None, [(max(start, 0.0), end)]),
            "progress_hooks": [lambda _d: progress.check()]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.twitch.tv/videos/{video_id}"])
    if not target.exists():
        raise RuntimeError("extrait de rediffusion introuvable")
    return target


def fetch_window(clip, dest_dir: Path) -> Window:
    """Extrait léger de la rediffusion autour du clip, sinon le clip (version légère)."""
    from . import progress
    from .download import download_preview, has_audio
    from .render import probe_duration

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if has_vod(clip):
        before = min(BEFORE, clip.vod_offset)
        start = clip.vod_offset - before
        try:
            path = _vod_range(clip.video_id, start, clip.vod_offset + clip.duration + AFTER,
                              dest_dir / f"{clip.id}-win.mp4", WINDOW_FORMAT)
            length = probe_duration(path)
            if has_audio(path) and length >= clip.duration:
                return Window(path, start, length, (before, min(before + clip.duration, length)))
            raise RuntimeError(f"extrait incomplet ({length:.0f} s)")
        except progress.Cancelled:
            raise
        except Exception as exc:
            log.info("Rediffusion indisponible pour %s (%s) : clip Twitch utilisé", clip.id, exc)
    path = download_preview(clip.url, dest_dir, clip.id)
    length = probe_duration(path) or clip.duration
    return Window(Path(path), None, length, (0.0, length))


# --- 3. phrases ------------------------------------------------------------------------------

def phrases(words: list, gap: float = PHRASE_GAP) -> list[tuple[float, float, str]]:
    """Mots → phrases (début, fin, texte) : une pause ou une ponctuation finale coupe."""
    out, cur = [], []
    for w in words:
        if cur and (w.start - cur[-1].end >= gap or cur[-1].text.strip()[-1:] in ".?!…"):
            out.append((cur[0].start, cur[-1].end, " ".join(x.text.strip() for x in cur)))
            cur = []
        cur.append(w)
    if cur:
        out.append((cur[0].start, cur[-1].end, " ".join(x.text.strip() for x in cur)))
    return out


def timed_lines(words: list, limit: int = 1800) -> str:
    """« [12.3 → 15.8] texte » par phrase, pour que Claude choisisse le début et la fin."""
    lines = [f"[{a:.1f} → {b:.1f}] {t}" for a, b, t in phrases(words)]
    text = "\n".join(lines)
    if len(text) > limit:  # rare (extrait très bavard) : début et fin gardés
        text = text[: limit // 2] + "\n…\n" + text[-limit // 2:]
    return text


# --- 4. découpe sans Claude --------------------------------------------------------------------

def _active(audio, sample_rate: int):
    """Secondes (par 0,25 s) où il y a du son au-dessus du bruit de fond (rire, cri…)."""
    import numpy as np

    win = sample_rate // 4
    n = len(audio) // win
    if n == 0:
        return np.zeros(0, dtype=bool)
    rms = np.sqrt(np.mean(np.square(audio[: n * win].reshape(n, win)), axis=1))
    return rms >= max(2 * float(np.median(rms)), 0.25 * float(np.percentile(rms, 95)), 1e-4)


def auto_cut(window: Window, words: list, audio=None, sample_rate: int = 16000) -> tuple[float, float]:
    """Début et fin (s dans l'extrait) sans Claude : on remonte au début de la phrase en
    cours (et de celles qui s'enchaînent sans pause) quand le clip démarre en pleine
    phrase, on va jusqu'à la fin de la dernière phrase et de la réaction qui suit."""
    s0, s1 = window.span
    ph = phrases(words)
    start, end = s0, s1
    i = next((k for k, p in enumerate(ph) if p[0] < s0 < p[1] + 0.3), None)
    if i is not None:
        start = ph[i][0]
        while i > 0 and start - ph[i - 1][1] < PHRASE_GAP and s0 - ph[i - 1][0] <= 10:
            i -= 1
            start = ph[i][0]
    j = next((k for k, p in enumerate(ph) if p[0] - 0.3 < s1 < p[1]), None)
    if j is not None:
        end = ph[j][1]
        while j + 1 < len(ph) and ph[j + 1][0] - end < PHRASE_GAP and ph[j + 1][1] - s1 <= 8:
            j += 1
            end = ph[j][1]
    if audio is not None:  # la réaction (rire, cri) n'est pas toujours transcrite
        active = _active(audio, sample_rate)
        k = int(end / 0.25)
        limit = min(len(active), int((end + 5) / 0.25))
        while k < limit and active[k]:
            k += 1
        end = max(end, k * 0.25)
    return clamp_cut(window, max(start - 0.3, 0.0), end + 1.0)


def clamp_cut(window: Window, start: float, end: float) -> tuple[float, float]:
    """Début / fin ramenés dans l'extrait, entre 10 et 60 s (la fin est gardée en priorité :
    c'est la chute et la réaction)."""
    start = min(max(float(start), 0.0), window.length)
    end = min(max(float(end), start), window.length)
    if end - start > MAX_LEN:
        start = end - MAX_LEN
    if end - start < MIN_LEN:  # trop court : on élargit autour du clip d'origine
        mid = (window.span[0] + window.span[1]) / 2
        start = max(min(start, mid - MIN_LEN / 2), 0.0)
        end = min(max(end, start + MIN_LEN), window.length)
    return round(start, 2), round(end, 2)


# --- 5. version finale -------------------------------------------------------------------------

def final_video(clip, dest_dir: Path) -> Path:
    """Version 1080p du passage choisi. ``clip.render_cut`` = (début dans le fichier,
    durée) à donner au montage."""
    from .download import download_clip, locate
    from .subtitles import SAMPLE_RATE, load_audio

    dest_dir = Path(dest_dir)
    window: Window | None = getattr(clip, "window", None)
    cut = getattr(clip, "cut", None)
    if window is None or not Path(window.path).exists():
        window = fetch_window(clip, dest_dir)  # clip déjà jugé lors d'une autre recherche
        clip.window = window
        if cut is None:
            cut = clip.cut = auto_cut(window, [], load_audio(window.path), SAMPLE_RATE)
    if cut is None:
        cut = (window.span[0], window.span[1])
    start, end = cut
    try:
        if window.vod_start is not None:
            target = dest_dir / f"{clip.id}.mp4"
            try:
                a = window.vod_start + start - PAD
                _vod_range(clip.video_id, a, window.vod_start + end + PAD, target, FINAL_FORMAT)
                small = load_audio(window.path)
                piece = small[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
                at = locate(piece, load_audio(target), SAMPLE_RATE)
                if at is None:
                    raise RuntimeError("passage non retrouvé dans la version 1080p")
                clip.render_cut = (at, round(end - start, 2))
                clip.vod_added = round(max(window.span[0] - start, 0), 1) or None
                log.info("Clip découpé dans la rediffusion : %.1f s → %.1f s (clip Twitch : "
                         "%.1f s → %.1f s)", start, end, *window.span)
                return target
            except Exception as exc:
                from . import progress

                if isinstance(exc, progress.Cancelled):
                    raise
                log.warning("Version 1080p de la rediffusion impossible (%s) : clip Twitch", exc)
                target.unlink(missing_ok=True)
                # repli : le clip Twitch, coupé au mieux dans ses propres limites
                s0 = window.span[0]
                start, end = max(start - s0, 0.0), max(end - s0, 1.0)
        path = download_clip(clip.url, dest_dir, clip.id)
        clip.render_cut = (round(start, 2), round(end - start, 2))
        return path
    finally:
        Path(window.path).unlink(missing_ok=True)
        Path(dest_dir / f"{clip.id}-small.mp4").unlink(missing_ok=True)
