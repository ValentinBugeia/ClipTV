"""Pilote automatique : tout de A à Z, sans intervention.

Toutes les ``every`` minutes, il cherche les clips les plus viraux des chaînes suivies,
les télécharge, les sous-titre, les recadre, écrit la légende (Claude) puis les
programme sur les prochains créneaux libres (ou les publie tout de suite). En
parallèle, il surveille les lives choisis et clippe chaque pic de chat. Le
planificateur publie ensuite chaque clip à l'heure prévue.

Les réglages sont modifiables depuis l'interface web (page « Pilote auto ») et
enregistrés en base ; les variables d'environnement ne servent que de valeurs
initiales.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

from .config import Config
from .pipeline import Options
from .state import State

log = logging.getLogger("clipbot.autopilot")


def _env_list(name: str) -> list[str]:
    return [c.lower() for c in re.split(r"[\s,]+", os.environ.get(name, "")) if c]


def default_settings(cfg: Config) -> dict:
    return {
        "enabled": os.environ.get("CLIPBOT_AUTOPILOT", "").lower() in ("1", "true", "yes", "on"),
        # discover = trouve seul les temps forts des streams les plus regardés ;
        # channels = seulement les chaînes listées
        "source": "discover",
        "language": os.environ.get("CLIPBOT_LANGUAGE", "fr"),
        "streamers": 30,         # lives les plus regardés scannés à chaque passage
        "channels": _env_list("CLIPBOT_CHANNELS"),
        "live_channels": _env_list("CLIPBOT_WATCH_CHANNELS"),
        "every": 60,             # minutes entre deux recherches
        "hours": 24,             # fenêtre de recherche des clips
        "top": 3,                # clips max par recherche (par chaîne en mode channels)
        "min_views": 50,
        "then": "schedule",      # schedule | publish | manual (tu publies toi-même)
        "ai_caption": True,
        "subtitles": True,       # sous-titres animés de l'app
        "layout": "auto",        # auto (facecam en haut sinon zoom) | crop (zoom) | blur
        "ratio": 3.0,            # sensibilité de la détection de pics de chat
        "platforms": list(cfg.platforms),
        "post_slots": list(cfg.post_slots),
        "max_queue": 0,          # clips programmés max (0 = 2 jours de créneaux)
    }


def load_settings(state: State, cfg: Config) -> dict:
    return {**default_settings(cfg), **state.get_settings()}


def apply_settings(cfg: Config, settings: dict) -> None:
    """Les créneaux et plateformes choisis dans l'interface s'appliquent partout."""
    if settings.get("platforms"):
        cfg.platforms = list(settings["platforms"])
    if settings.get("post_slots"):
        cfg.post_slots = list(settings["post_slots"])


def max_queue(settings: dict) -> int:
    return int(settings.get("max_queue") or 2 * max(len(settings.get("post_slots") or []), 1))


class Autopilot:
    def __init__(self, cfg: Config, state: State, base_opts: Options, tick: float = 30):
        self.cfg, self.state, self.base_opts, self.tick = cfg, state, base_opts, tick
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.force = False
        self.searching = False
        self.message = "Démarrage…"
        self.last_run: float | None = None
        self.next_run: float | None = None
        self.live_status: dict[str, str] = {}
        self._watchers: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._watch_key = ""

    # ---------- contrôle ----------
    def start(self) -> None:
        threading.Thread(target=self._loop, name="autopilot", daemon=True).start()

    def run_now(self) -> None:
        self.force = True
        self.wake.set()

    def refresh(self) -> None:
        """Réglages modifiés : on les prend en compte tout de suite."""
        self.wake.set()

    def shutdown(self) -> None:
        self.stop.set()
        self.wake.set()
        self._sync_watchers({"enabled": False})

    # ---------- boucle ----------
    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                self._step()
            except Exception:  # le pilote ne doit jamais s'arrêter
                log.exception("Erreur du pilote automatique")
            self.wake.wait(self.tick)
            self.wake.clear()

    def _step(self) -> None:
        from . import stats

        if stats.due(self.state) and self.cfg.tiktok_token_path.exists():
            stats.refresh(self.cfg, self.state)  # statistiques TikTok, toutes les heures
        settings = load_settings(self.state, self.cfg)
        apply_settings(self.cfg, settings)
        self._sync_watchers(settings)
        if not settings["enabled"]:
            self.message, self.next_run = "En pause", None
            self.force = False
            return
        every = max(float(settings["every"]), 5) * 60
        due = self.last_run is None or time.time() - self.last_run >= every
        if due or self.force:
            self.force = False
            self.last_run = time.time()
            self._search(settings)
        self.next_run = self.last_run + every

    def _options(self, settings: dict) -> Options:
        from .pipeline import tiktok_mode

        # publication directe : TikTok exige que l'utilisateur choisisse les réglages de
        # chaque vidéo (écran « Publier sur TikTok ») → les clips restent « À valider »
        direct = ("tiktok" in settings["platforms"]
                  and tiktok_mode(self.state, self.base_opts) == "direct")
        return Options(**{**self.base_opts.__dict__,
                          "ai_caption": bool(settings["ai_caption"]),
                          "publish": settings["then"] == "publish" and not direct,
                          "schedule": settings["then"] == "schedule" and not direct,
                          "platforms": list(settings["platforms"]),
                          "layout": settings.get("layout", "auto"),
                          "subtitles": bool(settings.get("subtitles", True))})

    def _search(self, settings: dict) -> None:
        from .pipeline import run_channels
        from .twitch import TwitchClient

        channels = settings["channels"]
        discover = settings.get("source", "discover") == "discover"
        if not discover and not channels:
            self.message = "Aucune chaîne à suivre : ajoute-en ou passe en découverte auto"
            return
        limit = max_queue(settings)
        queued = self._pending(settings)
        if settings["then"] != "publish" and queued >= limit:
            what = "à publier" if settings["then"] == "manual" else "programmés"
            self.message = (f"File d'attente pleine ({queued} clips {what}) : "
                            "recherche reportée")
            return
        if not (self.cfg.twitch_client_id and self.cfg.twitch_client_secret):
            self.message = "Clés Twitch manquantes (TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET)"
            return
        from . import progress

        self.searching = True
        progress.begin("Pilote automatique")
        try:
            twitch = TwitchClient(self.cfg.twitch_client_id, self.cfg.twitch_client_secret)
            opts = self._options(settings)
            done, errors = 0, []
            if discover:
                done, errors = self._discover(settings, opts, twitch, limit)
                channels = []
            for i, channel in enumerate(channels, 1):
                if self.stop.is_set():
                    return
                self.message = f"Recherche en cours : {channel} ({i}/{len(channels)})…"
                # ne remplit pas la file au-delà de la limite
                top = int(settings["top"])
                if not opts.publish:
                    top = min(top, limit - self._pending(settings))
                    if top <= 0:
                        break
                try:
                    results = run_channels([channel], self.cfg, self.state, opts, twitch,
                                           hours=float(settings["hours"]), top=top,
                                           min_views=int(settings["min_views"]))
                except Exception as exc:
                    log.exception("Recherche échouée pour %s", channel)
                    from .errors import explain

                    errors.append(f"{channel} : {explain(exc)}")
                    continue
                done += sum(ok for _, ok in results)
                errors += [f"{channel} (clip {cid})" for cid, ok in results if not ok]
            verb = {"publish": "publié(s)", "manual": "prêt(s) à publier"}.get(
                settings["then"], "programmé(s)")
            self.message = f"Dernière recherche : {done} nouveau(x) clip(s) {verb}"
            if errors:  # visible sur la page ; détail de chaque clip dans l'onglet Erreurs
                self.message += " · ⚠️ " + " | ".join(errors[:2])
        except progress.Cancelled:  # bouton « Arrêter » : prochaine recherche à l'heure prévue
            self.message = "Recherche arrêtée"
        finally:
            self.searching = False
            progress.end(self.message)

    def _pending(self, settings: dict) -> int:
        """Clips en attente : programmés, ou prêts à publier à la main."""
        from .pipeline import tiktok_mode

        review = settings["then"] == "manual" or (
            "tiktok" in settings["platforms"]
            and tiktok_mode(self.state, self.base_opts) == "direct")
        return self.state.count("rendered" if review else "scheduled")

    def _discover(self, settings: dict, opts: Options, twitch, limit: int):
        from .discover import run_discovery

        top = int(settings["top"])
        if not opts.publish:
            top = min(top, limit - self._pending(settings))
            if top <= 0:
                return 0, []
        lang = settings.get("language") or None
        self.message = f"Recherche des temps forts ({lang or 'toutes langues'})…"
        try:
            results = run_discovery(self.cfg, self.state, opts, twitch, language=lang,
                                    streamers=int(settings.get("streamers", 30)),
                                    hours=float(settings["hours"]), top=top,
                                    min_views=int(settings["min_views"]),
                                    favorites=settings["channels"])
        except Exception as exc:
            log.exception("Découverte échouée")
            from .errors import explain

            return 0, [f"recherche des temps forts : {explain(exc)}"]
        return (sum(ok for _, ok in results),
                [f"clip {cid}" for cid, ok in results if not ok])

    # ---------- lives ----------
    def _sync_watchers(self, settings: dict) -> None:
        wanted = set(settings.get("live_channels") or []) if settings.get("enabled") else set()
        key = json.dumps({k: settings.get(k) for k in
                          ("ratio", "then", "ai_caption", "platforms", "layout", "subtitles")}, sort_keys=True)
        if key != self._watch_key:  # réglages changés : on relance les surveillances
            self._watch_key = key
            self._apply_watchers(set())
        self._apply_watchers(wanted, settings)

    def _apply_watchers(self, wanted: set[str], settings: dict | None = None) -> None:
        for channel in list(self._watchers):
            thread, stop = self._watchers[channel]
            if channel not in wanted or not thread.is_alive():
                stop.set()
                del self._watchers[channel]
                self.live_status.pop(channel, None)
        missing = wanted - set(self._watchers)
        if not missing or settings is None:
            return
        if not self.cfg.twitch_token_path.exists():
            for channel in missing:
                self.live_status[channel] = "⚠️ connecte ton compte Twitch (page Comptes)"
            return
        from .twitch import TwitchClient, TwitchUserAuth
        from .watcher import WatchParams, watch_channel

        auth = TwitchUserAuth(self.cfg.twitch_client_id, self.cfg.twitch_client_secret,
                              self.cfg.twitch_token_path)
        opts = self._options(settings)
        params = WatchParams(ratio=float(settings["ratio"]), forever=True)
        for channel in sorted(missing):
            stop = threading.Event()
            twitch = TwitchClient(self.cfg.twitch_client_id, self.cfg.twitch_client_secret)
            thread = threading.Thread(
                target=watch_channel, name=f"live-{channel}", daemon=True,
                args=(channel, self.cfg, self.state, opts, twitch, auth, params, stop,
                      self.live_status))
            self.live_status[channel] = "démarrage…"
            thread.start()
            self._watchers[channel] = (thread, stop)
