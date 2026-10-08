"""Transcription (faster-whisper) et génération de sous-titres ASS style TikTok.

Les mots sont regroupés en petits blocs (2-3 mots) affichés en gros au centre,
le mot en cours de prononciation est surligné en couleur. Les mots forts (« NON », « MDR »,
« QUOI », cris…) ressortent dans une autre couleur et grossissent quand ils sont prononcés.
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


_models: dict = {}  # modèles Whisper déjà chargés (le chargement prend plusieurs secondes)


def _model(model_size: str, device: str):
    from faster_whisper import WhisperModel
    import os

    key = (model_size, device)
    if key not in _models:
        compute_type = "int8" if device in ("auto", "cpu") else "float16"
        _models[key] = WhisperModel(model_size, device=device, compute_type=compute_type,
                                    cpu_threads=os.cpu_count() or 4)
    return _models[key]


def transcribe(
    video: Path,
    *,
    model_size: str = "small",
    device: str = "auto",
    language: str | None = None,
    beam_size: int = 5,
    max_seconds: float | None = None,
) -> list[Word]:
    """``beam_size=1`` et ``max_seconds`` : transcription rapide (tri des clips)."""
    model = _model(model_size, device)
    audio = load_audio(video)
    if max_seconds:
        audio = audio[: int(max_seconds * SAMPLE_RATE)]
    if audio.size == 0:  # clip sans piste audio
        return []
    # beam_size : 3 pour les sous-titres (presque aussi précis que 5, nettement plus
    # rapide), 1 pour la transcription rapide du juré
    segments, _info = model.transcribe(
        audio, language=language, word_timestamps=True, vad_filter=True, beam_size=beam_size,
        condition_on_previous_text=False,  # évite les répétitions en boucle
    )
    from . import progress

    words: list[Word] = []
    for seg in segments:  # la transcription avance segment par segment
        progress.check()  # bouton « Arrêter »
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


STRONG_WORDS = {
    "non", "nan", "nooon", "quoi", "wtf", "omg", "putain", "merde", "bordel", "purée", "sérieux",
    "sérieusement", "jamais", "incroyable", "impossible", "attends", "arrête", "stop", "pourquoi",
    "oh", "ah", "aïe", "oula", "ouf", "dingue", "dinguerie", "fou", "folle", "énorme", "chaud",
    "help", "gg", "mdr", "ptdr", "jpp", "lol", "xd", "nul", "honteux", "masterclass", "monstre",
}


def is_strong(text: str) -> bool:
    """Mot de réaction : exclamation, rire, cri (« noooon », « aaah »), juron…"""
    import re

    from .live import LAUGH_RE

    word = re.sub(r"[^\w'+]", "", text.lower())
    if not word:
        return False
    return (word in STRONG_WORDS or bool(LAUGH_RE.match(word))
            or bool(re.search(r"(\w)\1{2,}", word)) or text.rstrip().endswith("!"))


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
Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,{hook_margin},1

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
    strong: str | None = "#FF4F7B",
    uppercase: bool = True,
    margin_v: int = 560,
    hook: str = "",
    hook_seconds: float = 3.0,
    hook_margin: int = 260,
) -> str:
    """``hook`` : titre d'accroche affiché en haut pendant ``hook_seconds`` secondes.
    ``strong`` : couleur des mots forts (None = comme les autres mots)."""
    out = [
        ASS_HEADER.format(
            width=width,
            height=height,
            font=font,
            size=font_size,
            outline=max(font_size // 14, 4),
            margin_v=margin_v,
            hook_size=round(font_size * 0.82),
            hook_margin=hook_margin,
        )
    ]
    if hook:  # bandeau noir, texte blanc : lisible sur n'importe quelle image
        out.append(f"Dialogue: 1,{_ts(0)},{_ts(hook_seconds)},Hook,,0,0,0,,"
                   f"{{\\fad(0,250)}}{_escape(hook)}\n")
    hl = _ass_color(highlight)
    st = _ass_color(strong) if strong else None
    white = "&H00FFFFFF&"
    for group in group_words(words):
        texts = [_escape(w.text.upper() if uppercase else w.text) for w in group]
        strongs = [bool(st) and is_strong(w.text) for w in group]
        for i, word in enumerate(group):
            start = word.start
            # le bloc reste affiché jusqu'au mot suivant (pas de clignotement)
            end = group[i + 1].start if i + 1 < len(group) else word.end
            if end <= start:
                end = start + 0.05
            parts = []
            for j, t in enumerate(texts):
                if strongs[j] and j == i:  # mot fort prononcé : couleur + grossit d'un coup
                    parts.append(f"{{\\c{st}\\fscx130\\fscy130\\t(0,140,\\fscx115\\fscy115)}}"
                                 f"{t}{{\\c{white}\\fscx100\\fscy100}}")
                elif strongs[j]:
                    parts.append(f"{{\\c{st}}}{t}{{\\c{white}}}")
                elif j == i:
                    parts.append(f"{{\\c{hl}}}{t}{{\\c{white}}}")
                else:
                    parts.append(t)
            # petit effet "pop" à l'apparition du bloc
            prefix = "{\\fscx110\\fscy110\\t(0,80,\\fscx100\\fscy100)}" if i == 0 else ""
            out.append(
                f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{prefix}{' '.join(parts)}\n"
            )
    return "".join(out)


def write_ass(words: list[Word], path: Path, **kwargs) -> Path:
    path.write_text(build_ass(words, **kwargs), encoding="utf-8")
    return path


def warm_up(model_size: str, device: str = "auto") -> None:
    """Charge les modèles Whisper en arrière-plan au lancement de l'app : la première
    recherche n'attend plus leur chargement (ni leur téléchargement la toute première fois)."""
    import logging
    import threading

    def run():
        for size in dict.fromkeys((model_size, "base")):
            try:
                _model(size, device)
            except Exception:
                logging.getLogger("clipbot").info("Préchargement Whisper %s impossible", size,
                                                  exc_info=True)
    threading.Thread(target=run, daemon=True, name="whisper-warmup").start()
