"""Surveillance du chat Twitch en direct pour détecter les moments viraux.

Principe : un moment fort fait exploser le chat (spam d'emotes, "KEKW", "CLIP",
"mdrrr"...). On compare l'activité des dernières secondes à la moyenne glissante de
la chaîne ; au-delà d'un seuil, on crée un clip Twitch (les ~30 s précédentes).
"""

from __future__ import annotations

import logging
import random
import re
import socket
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator

log = logging.getLogger("clipbot.live")

IRC_HOST, IRC_PORT = "irc.chat.twitch.tv", 6667

HYPE_TOKENS = {
    # emotes / réactions courantes
    "kekw", "lul", "lulw", "omegalul", "pog", "pogu", "poggers", "pogchamp", "monkas",
    "pepelaugh", "kappa", "wutface", "ez", "gg", "w", "l", "ratio", "sheesh", "letsgo",
    "clip", "clipit", "+1", "xd", "lmao", "lol", "wtf", "omg",
    # français
    "mdr", "ptdr", "jpp", "ouf", "dinguerie", "incroyable", "masterclass", "chaud",
}
LAUGH_RE = re.compile(r"^(?:a?h(?:a|e|i)){2,}h?$|^(?:mdr+|ptdr+|x+d+|lo+l+|ja+ja+)$", re.I)
PRIVMSG_RE = re.compile(r"^(?:@\S+ )?:(\w+)!\S+ PRIVMSG #(\w+) :(.*)$")


def message_weight(text: str) -> float:
    """Poids d'un message : 1 de base, plus s'il exprime une réaction forte."""
    tokens = re.findall(r"[\w+]+", text.lower())
    weight = 1.0
    if any(t in HYPE_TOKENS or LAUGH_RE.match(t) for t in tokens):
        weight += 1.0
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        weight += 0.5  # CRIS EN MAJUSCULES
    if re.search(r"(.)\1{3,}", text):
        weight += 0.5  # "nooooon", "!!!!!"
    return weight


@dataclass
class SpikeDetector:
    """Détecte un pic d'activité pondérée dans le chat.

    - ``window`` : durée (s) de la fenêtre "récente"
    - ``baseline_window`` : durée (s) servant à calculer l'activité normale
    - ``ratio`` : multiplicateur au-dessus de la normale pour déclencher
    - ``min_score`` : score minimal par seconde (évite les faux positifs sur petits chats)
    - ``cooldown`` : délai minimal entre deux déclenchements
    - ``warmup`` : temps d'observation avant le premier déclenchement possible
    """

    window: float = 10.0
    baseline_window: float = 300.0
    ratio: float = 3.0
    min_score: float = 1.5
    cooldown: float = 90.0
    warmup: float = 60.0
    _events: deque = field(default_factory=deque)
    _start: float | None = None
    _last_trigger: float = float("-inf")

    def add(self, ts: float, weight: float) -> None:
        if self._start is None:
            self._start = ts
        self._events.append((ts, weight))
        while self._events and self._events[0][0] < ts - self.baseline_window:
            self._events.popleft()

    def rates(self, now: float) -> tuple[float, float]:
        """(score/s sur la fenêtre récente, score/s de référence hors fenêtre récente)."""
        recent = sum(w for t, w in self._events if t >= now - self.window)
        older = sum(w for t, w in self._events if t < now - self.window)
        start = self._start if self._start is not None else now
        observed = min(now - start, self.baseline_window) - self.window
        baseline = older / observed if observed > 0 else 0.0
        return recent / self.window, baseline

    def check(self, now: float) -> float | None:
        """Retourne l'intensité du pic (ratio) si un clip doit être créé, sinon None."""
        if self._start is None or now - self._start < self.warmup:
            return None
        if now - self._last_trigger < self.cooldown:
            return None
        recent, baseline = self.rates(now)
        threshold = max(self.min_score, baseline * self.ratio)
        if recent >= threshold:
            self._last_trigger = now
            return recent / baseline if baseline else float("inf")
        return None


def read_chat(channel: str, *, timeout: float = 1.0) -> Iterator[tuple[float, str, str] | None]:
    """Se connecte anonymement au chat IRC et génère (timestamp, user, message).

    Génère ``None`` régulièrement quand le chat est silencieux, pour que l'appelant
    puisse vérifier le détecteur même sans nouveau message.
    """
    while True:
        sock = None
        try:
            sock = socket.create_connection((IRC_HOST, IRC_PORT), timeout=30)
            sock.settimeout(timeout)
            nick = f"justinfan{random.randint(10000, 99999)}"
            sock.sendall(f"NICK {nick}\r\nJOIN #{channel.lower()}\r\n".encode())
            log.info("Connecté au chat de #%s", channel)
            buf = ""
            while True:
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    yield None
                    continue
                if not data:
                    raise ConnectionError("connexion IRC fermée")
                buf += data.decode("utf-8", errors="ignore")
                *lines, buf = buf.split("\r\n")
                for line in lines:
                    if line.startswith("PING"):
                        sock.sendall(line.replace("PING", "PONG", 1).encode() + b"\r\n")
                        continue
                    m = PRIVMSG_RE.match(line)
                    if m:
                        yield time.time(), m.group(1), m.group(3)
                yield None
        except (OSError, ConnectionError) as exc:
            log.warning("Chat déconnecté (%s), reconnexion dans 5 s", exc)
            time.sleep(5)
        finally:  # aussi quand l'appelant arrête la lecture (generator.close())
            if sock is not None:
                sock.close()


BUCKET = 10  # secondes


class ChatRecorder:
    """Écoute en continu le chat de plusieurs lives (une seule connexion IRC anonyme) et
    enregistre l'activité pondérée par tranches de 10 s. Sert à savoir, après coup, si le
    chat a explosé au moment où un clip a été créé (le meilleur signal d'un moment fort).
    """

    def __init__(self, state, flush_every: float = 60):
        import threading

        self.state, self.flush_every = state, flush_every
        self.wanted: set[str] = set()
        self.joined: set[str] = set()
        self.buckets: dict[tuple[str, int], float] = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def set_channels(self, channels) -> None:
        with self.lock:
            self.wanted = {c.lower() for c in channels if c}

    def start(self) -> None:
        import threading

        threading.Thread(target=self._run, name="chat-recorder", daemon=True).start()

    def add(self, channel: str, ts: float, text: str) -> None:
        key = (channel.lower(), int(ts // BUCKET * BUCKET))
        with self.lock:
            self.buckets[key] = self.buckets.get(key, 0.0) + message_weight(text)

    def flush(self) -> None:
        with self.lock:
            rows = [(c, b, w) for (c, b), w in self.buckets.items()]
            self.buckets = {}
        if rows:
            self.state.add_chat_activity(rows)

    def _run(self) -> None:
        last_flush = time.time()
        while not self.stop.is_set():
            sock = None
            try:
                sock = socket.create_connection((IRC_HOST, IRC_PORT), timeout=30)
                sock.settimeout(1.0)
                sock.sendall(f"NICK justinfan{random.randint(10000, 99999)}\r\n".encode())
                self.joined = set()
                buf = ""
                while not self.stop.is_set():
                    self._sync_joins(sock)
                    try:
                        data = sock.recv(8192)
                        if not data:
                            raise ConnectionError("connexion IRC fermée")
                        buf += data.decode("utf-8", errors="ignore")
                        *lines, buf = buf.split("\r\n")
                        now = time.time()
                        for line in lines:
                            if line.startswith("PING"):
                                sock.sendall(line.replace("PING", "PONG", 1).encode() + b"\r\n")
                                continue
                            m = PRIVMSG_RE.match(line)
                            if m:
                                self.add(m.group(2), now, m.group(3))
                    except socket.timeout:
                        pass
                    if time.time() - last_flush >= self.flush_every:
                        last_flush = time.time()
                        self.flush()
            except (OSError, ConnectionError) as exc:
                log.warning("Enregistreur de chat déconnecté (%s), reconnexion dans 10 s", exc)
                self.stop.wait(10)
            finally:
                if sock is not None:
                    sock.close()
        self.flush()

    def _sync_joins(self, sock) -> None:
        """Rejoint / quitte les chats demandés, doucement (limite de Twitch sur les JOIN)."""
        with self.lock:
            to_join = sorted(self.wanted - self.joined)[:5]
            to_part = sorted(self.joined - self.wanted)
        for c in to_part:
            sock.sendall(f"PART #{c}\r\n".encode())
            self.joined.discard(c)
        if to_join and time.time() - getattr(self, "_last_join", 0) >= 2:
            self._last_join = time.time()
            for c in to_join:
                sock.sendall(f"JOIN #{c}\r\n".encode())
                self.joined.add(c)


def chat_spike(state, channel: str, at: float) -> float | None:
    """Activité du chat juste avant la création du clip (fenêtre de 60 s), comparée à
    l'activité habituelle de la chaîne sur les 2 heures précédentes. None si le chat
    n'était pas écouté à ce moment-là."""
    from statistics import median

    buckets = state.chat_activity(channel, at - 7200, at + BUCKET)
    if len(buckets) < 30:  # moins de 5 min d'écoute : pas assez pour comparer
        return None
    moment = [w for b, w in buckets.items() if at - 60 <= b <= at]
    if not moment:
        return None
    usual = [w for b, w in buckets.items() if b < at - 60] or [0.0]
    base = max(median(usual), 1.0)
    return round(max(moment) / base, 2)
