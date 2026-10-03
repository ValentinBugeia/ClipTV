"""Transcription (faster-whisper) et génération de sous-titres ASS style TikTok.

Les mots sont regroupés en petits blocs (2-3 mots) affichés en gros au centre,
le mot en cours de prononciation est surligné en couleur.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Word:
    text: str
    start: float
    end: float


SAMPLE_RATE = 16000  # fréquence attendue par Whisper


def load_audio(video: Path):
    """Piste audio en mono 16 kHz (numpy float32), extraite avec ffmpeg.

    On ne laisse pas faster-whisper décoder lui-même : il passe par PyAV, dont les
    versions récentes (installées avec Python 3.14) ont retiré une option qu'il utilise
    (« open() got an unexpected keyword argument 'metadata_errors' »).
    """
    import subprocess

    import numpy as np

    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Extraction audio impossible : {proc.stderr.decode()[-300:]}")
    return np.frombuffer(proc.stdout, np.int16).astype(np.float32) / 32768.0


def transcribe(
    video: Path,
    *,
    model_size: str = "small",
    device: str = "auto",
    language: str | None = None,
) -> list[Word]:
    from faster_whisper import WhisperModel

    compute_type = "int8" if device in ("auto", "cpu") else "float16"
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    audio = load_audio(video)
    if audio.size == 0:  # clip sans piste audio
        return []
    segments, _info = model.transcribe(
        audio, language=language, word_timestamps=True, vad_filter=True
    )
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(text=text, start=float(w.start), end=float(w.end)))
    return words


def group_words(
    words: list[Word], *, max_words: int = 3, max_duration: float = 1.6, max_gap: float = 0.6
) -> list[list[Word]]:
    """Découpe la liste de mots en blocs courts, lisibles sur mobile."""
    groups: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current:
            too_many = len(current) >= max_words
            too_long = word.end - current[0].start > max_duration
            gap = word.start - current[-1].end > max_gap
            ends_sentence = current[-1].text.endswith((".", "!", "?", "…"))
            if too_many or too_long or gap or ends_sentence:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _ts(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ass_color(hex_rgb: str) -> str:
    """'#RRGGBB' -> '&H00BBGGRR' (format ASS)."""
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},3,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(
    words: list[Word],
    *,
    width: int = 1080,
    height: int = 1920,
    font: str = "Montserrat Black",
    font_size: int = 88,
    highlight: str = "#FFE600",
    uppercase: bool = True,
    margin_v: int = 560,
) -> str:
    out = [
        ASS_HEADER.format(
            width=width,
            height=height,
            font=font,
            size=font_size,
            outline=max(font_size // 14, 4),
            margin_v=margin_v,
        )
    ]
    hl = _ass_color(highlight)
    for group in group_words(words):
        texts = [_escape(w.text.upper() if uppercase else w.text) for w in group]
        for i, word in enumerate(group):
            start = word.start
            # le bloc reste affiché jusqu'au mot suivant (pas de clignotement)
            end = group[i + 1].start if i + 1 < len(group) else word.end
            if end <= start:
                end = start + 0.05
            parts = [
                f"{{\\c{hl}}}{t}{{\\c&H00FFFFFF&}}" if j == i else t for j, t in enumerate(texts)
            ]
            # petit effet "pop" à l'apparition du bloc
            prefix = "{\\fscx110\\fscy110\\t(0,80,\\fscx100\\fscy100)}" if i == 0 else ""
            out.append(
                f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{prefix}{' '.join(parts)}\n"
            )
    return "".join(out)


def write_ass(words: list[Word], path: Path, **kwargs) -> Path:
    path.write_text(build_ass(words, **kwargs), encoding="utf-8")
    return path
