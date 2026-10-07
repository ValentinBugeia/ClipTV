"""Conversion en vertical 9:16 (1080x1920) + incrustation des sous-titres avec ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

WIDTH, HEIGHT = 1080, 1920


def build_filter(
    layout: str = "blur",
    subtitles: str | None = None,
    *,
    cam_box: tuple[int, int, int, int] | None = None,
    crop_center: float | None = None,
    crop_track: list[tuple[float, float]] | None = None,
    cam_height: int | None = None,
    punch_at: float | None = None,
    emoji_at: float | None = None,
) -> str:
    """Construit le filtergraph ffmpeg.

    ``emoji_at`` : un emoji (2e entrée, image PNG) surgit au-dessus des sous-titres à cette
    seconde pendant 1,2 s.

    ``punch_at`` : seconde de la réaction la plus forte → petit zoom « impact » d'une
    demi-seconde (effet de montage : rythme, et contenu transformé aux yeux de TikTok).

    - ``blur`` : la vidéo 16:9 est centrée, le fond est la même vidéo zoomée et floutée
      (format le plus courant pour les clips de stream).
    - ``crop`` : zoom plein écran (recadrage sur le centre ou sur le visage).
    - ``split`` : facecam en haut, gameplay en bas.

    ``cam_box`` = (w, h, x, y) de la facecam dans la source (sinon coin haut-droit) ;
    ``crop_center`` = position horizontale relative (0-1) à centrer en mode ``crop`` ;
    ``crop_track`` = [(secondes, position relative)] : le zoom suit le visage dans le temps.
    """
    # fps=30 en premier : les sources Twitch sont souvent en 60 i/s, on ne traite que les
    # images gardées. Partout on recadre AVANT d'agrandir : même image finale, mais
    # ffmpeg ne calcule plus une image géante (3413x1920) dont il jette les deux tiers.
    if layout == "blur":
        graph = (
            f"[0:v]fps=30,split=2[bg][fg];"
            # fond flou calculé en petit (il est flou de toute façon) puis agrandi
            f"[bg]crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={WIDTH // 4}:{HEIGHT // 4},"
            f"boxblur=5:2,eq=brightness=-0.08,scale={WIDTH}:{HEIGHT}[bgb];"
            f"[fg]scale={WIDTH}:-2[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
        )
    elif layout == "crop":
        x = ""
        center = track_expr(crop_track) if crop_track and len(crop_track) > 1 else (
            f"{crop_center:.4f}" if crop_center is not None else
            f"{crop_track[0][1]:.4f}" if crop_track else None)
        if center is not None:
            x = f":'min(max(({center})*iw-ow/2,0),iw-ow)':0"
        graph = (f"[0:v]fps=30,crop='min(iw,ih*9/16)':ih{x},"
                 f"scale={WIDTH}:{HEIGHT},setsar=1[v]")
    elif layout == "split":
        cam_h = cam_height or HEIGHT * 2 // 5
        game_h = HEIGHT - cam_h
        cam = "{}:{}:{}:{}".format(*cam_box) if cam_box else "iw/4:ih/4:iw*3/4:0"
        graph = (
            f"[0:v]fps=30,split=2[a][b];"
            f"[a]crop={cam},scale={WIDTH}:{cam_h}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{cam_h}[cam];"
            f"[b]crop='min(iw,ih*{WIDTH}/{game_h})':ih,scale={WIDTH}:{game_h}[game];"
            f"[cam][game]vstack,setsar=1[v]"
        )
    else:
        raise ValueError(f"Layout inconnu : {layout}")

    if punch_at is not None:
        a, b = punch_at, punch_at + 0.5
        zoom = f"(1+0.12*between(t,{a:.2f},{b:.2f}))"
        graph = (graph[: -len("[v]")] + f"[nz];[nz]scale=w='trunc({WIDTH}*{zoom}/2)*2'"
                 f":h='trunc({HEIGHT}*{zoom}/2)*2':eval=frame,crop={WIDTH}:{HEIGHT},setsar=1[v]")
    if subtitles:
        graph = graph[: -len("[v]")] + f"[pre];[pre]ass={_escape_filter_path(subtitles)}[v]"
    if emoji_at is not None:
        a, b = emoji_at, emoji_at + 1.2
        # grossit de 40 % à 110 % en 0,18 s puis se pose à 100 % : effet « pop »
        grow = (f"min(max(0.4,0.4+(t-{a:.2f})*4),"
                f"max(1,1.1-2*max(t-{a + 0.18:.2f},0)))")
        graph = (graph[: -len("[v]")] + f"[pre2];[1:v]format=rgba,"
                 f"fade=out:st={b - 0.25:.2f}:d=0.25:alpha=1,"
                 f"scale=w='trunc(230*{grow}/2)*2':h=-2:eval=frame[emo];"
                 f"[pre2][emo]overlay=x=(W-w)/2:y={HEIGHT // 2 + 30}-h/2:eval=frame:"
                 f"enable='between(t,{a:.2f},{b:.2f})':eof_action=pass,setsar=1[v]")
    return graph


def track_expr(track: list[tuple[float, float]]) -> str:
    """Expression ffmpeg de la position (0-1) en fonction de ``t`` : interpolation
    linéaire entre les points de la trajectoire, constante avant / après."""
    expr = f"{track[-1][1]:.4f}"
    for (t0, c0), (t1, c1) in reversed(list(zip(track, track[1:]))):
        if t1 <= t0:
            continue
        seg = f"{c0:.4f}+({c1 - c0:.4f})*(t-{t0:.2f})/{t1 - t0:.2f}"
        expr = f"if(lt(t,{t1:.2f}),{seg},{expr})"
    return f"if(lt(t,{track[0][0]:.2f}),{track[0][1]:.4f},{expr})"


def _escape_filter_path(path: str) -> str:
    return "'" + path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'") + "'"


def render_vertical(
    src: Path,
    dst: Path,
    *,
    layout: str = "blur",
    subtitles: Path | None = None,
    max_duration: float | None = None,
    fonts_dir: Path | None = None,
    cam_box: tuple[int, int, int, int] | None = None,
    crop_center: float | None = None,
    crop_track: list[tuple[float, float]] | None = None,
    cam_height: int | None = None,
    start: float = 0.0,
    normalize_audio: bool = True,
    punch_at: float | None = None,
    emoji: Path | None = None,
    emoji_at: float | None = None,
) -> Path:
    """``start`` : secondes coupées au début ; ``normalize_audio`` : volume égalisé
    (-14 LUFS, le niveau des vidéos TikTok) pour qu'aucun clip ne soit trop faible ou saturé."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if start and crop_track:  # la vidéo démarre plus tard : la trajectoire aussi
        later = [(t - start, c) for t, c in crop_track if t >= start]
        before = [c for t, c in crop_track if t < start]
        crop_track = ([(0.0, before[-1])] if before else []) + later or crop_track[-1:]
    graph = build_filter(layout, str(subtitles.resolve()) if subtitles else None,
                         cam_box=cam_box, crop_center=crop_center, crop_track=crop_track,
                         cam_height=cam_height, punch_at=punch_at,
                         emoji_at=emoji_at if emoji else None)
    if subtitles and fonts_dir:
        graph = graph.replace("ass=", f"ass=fontsdir={_escape_filter_path(str(fonts_dir.resolve()))}:filename=", 1)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", str(src)]
    if emoji and emoji_at is not None:  # image répétée juste le temps de l'apparition
        cmd += ["-loop", "1", "-t", f"{emoji_at + 1.5:.2f}", "-i", str(emoji)]
    if max_duration:
        cmd += ["-t", str(max_duration)]
    cmd += [
        "-filter_complex", graph,
        "-map", "[v]", "-map", "0:a?",
        # veryfast : ~40 % plus rapide que medium, TikTok réencode de toute façon
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", "30",
        *(["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"] if normalize_audio else []),
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-movflags", "+faststart",
        str(dst),
    ]
    _run_interruptible(cmd, dst)
    return dst


def _run_interruptible(cmd: list[str], dst: Path) -> None:
    """Lance ffmpeg ; le bouton « Arrêter » le coupe et supprime le fichier incomplet."""
    import time

    from . import progress

    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    while proc.poll() is None:
        if progress.cancelled():
            proc.kill()
            proc.wait()
            dst.unlink(missing_ok=True)
            raise progress.Cancelled()
        time.sleep(0.3)
    if proc.returncode != 0:
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=err)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())
