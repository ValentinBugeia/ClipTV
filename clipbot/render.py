"""Conversion en vertical 9:16 (1080x1920) + incrustation des sous-titres avec ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

WIDTH, HEIGHT = 1080, 1920


def build_filter(layout: str = "blur", subtitles: str | None = None) -> str:
    """Construit le filtergraph ffmpeg.

    - ``blur`` : la vidéo 16:9 est centrée, le fond est la même vidéo zoomée et floutée
      (format le plus courant pour les clips de stream).
    - ``crop`` : recadrage plein écran sur le centre de l'image.
    - ``split`` : facecam (coin haut-droit de la source) en haut, gameplay en bas.
    """
    if layout == "blur":
        graph = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},boxblur=20:2,eq=brightness=-0.08[bgb];"
            f"[fg]scale={WIDTH}:-2[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
        )
    elif layout == "crop":
        graph = (
            f"[0:v]scale=-2:{HEIGHT},crop={WIDTH}:{HEIGHT},setsar=1[v]"
        )
    elif layout == "split":
        cam_h = HEIGHT * 2 // 5
        game_h = HEIGHT - cam_h
        graph = (
            f"[0:v]split=2[a][b];"
            # facecam : quart haut-droit de l'image source
            f"[a]crop=iw/4:ih/4:iw*3/4:0,scale={WIDTH}:{cam_h}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{cam_h}[cam];"
            f"[b]scale=-2:{game_h},crop={WIDTH}:{game_h}[game];"
            f"[cam][game]vstack,setsar=1[v]"
        )
    else:
        raise ValueError(f"Layout inconnu : {layout}")

    if subtitles:
        graph = graph[: -len("[v]")] + f"[pre];[pre]ass={_escape_filter_path(subtitles)}[v]"
    return graph


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
) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    graph = build_filter(layout, str(subtitles.resolve()) if subtitles else None)
    if subtitles and fonts_dir:
        graph = graph.replace("ass=", f"ass=fontsdir={_escape_filter_path(str(fonts_dir.resolve()))}:filename=", 1)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if max_duration:
        cmd += ["-t", str(max_duration)]
    cmd += [
        "-filter_complex", graph,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True)
    return dst


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())
